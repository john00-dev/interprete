#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Intérprete EsJS
===============

Arquitectura (pipeline de 3 fases):

    texto fuente
        │
        ▼  Lexer.tokenize()
    lista de Tokens
        │
        ▼  Parser.parse()
    árbol de sintaxis ()
        │
        ▼  Interpreter.V()  
    efectos/salida


"""

import sys
import math
import re as _re


# ═══════════════════════════════════════════════════════════════════════
# 1. SEÑALES DE CONTROL DE FLUJO
# ═══════════════════════════════════════════════════════════════════════


class ReturnSignal(Exception):
    """Transporta el valor de un `retornar` hasta la llamada de función."""

    def __init__(self, value):
        self.value = value


class BreakSignal(Exception):
    """Emitida por `romper` para salir de un bucle o `elegir`."""


class ContinueSignal(Exception):
    """Emitida por `continuar` para saltar a la siguiente iteración."""


# ═══════════════════════════════════════════════════════════════════════
# 2. VALORES ESPECIALES
# ═══════════════════════════════════════════════════════════════════════


class _Undefined:
    """Singleton que representa `undefined` (EsJS: `indefinido`)."""

    _inst = None

    def __new__(cls):
        if not cls._inst:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return 'undefined'

    def __str__(self):
        return 'undefined'


class _Null:
    """Singleton que representa `null` (EsJS: `nulo`)."""

    _inst = None

    def __new__(cls):
        if not cls._inst:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return 'null'

    def __str__(self):
        return 'null'


UNDEFINED = _Undefined()
NULL = _Null()


# ═══════════════════════════════════════════════════════════════════════
# 3. OBJETOS EN TIEMPO DE EJECUCIÓN
# ═══════════════════════════════════════════════════════════════════════

class EsJSObject:
    """Objeto EsJS: diccionario de propiedades (`{ clave: valor }`)."""

    def __init__(self, props=None):
        self.props = dict(props) if props else {}

    def get_prop(self, key):
        return self.props.get(key, UNDEFINED)

    def set_prop(self, key, v):
        self.props[key] = v

    def __repr__(self):
        return '[object Object]'


class EsJSFunction:
    """Función definida por el usuario (declaración, expresión o flecha)."""

    def __init__(self, name, params, body, closure, is_arrow=False):
        self.name = name or 'anonymous'
        self.params = params
        self.body = body            # nodo Block o expresión (flecha corta)
        self.closure = closure      # entorno de definición (closure léxico)
        self.is_arrow = is_arrow

    def __repr__(self):
        return f'[Function: {self.name}]'


class BuiltinFunction:
    """Función nativa implementada en Python (`consola.escribir`, etc.)."""

    def __init__(self, name, fn):
        self.name = name
        self.fn = fn                # callable(args, this) -> valor

    def __repr__(self):
        return f'[NativeFunction: {self.name}]'


# ═══════════════════════════════════════════════════════════════════════
# 4. HELPERS DE COERCIÓN ESTILO JAVASCRIPT
# ═══════════════════════════════════════════════════════════════════════


def js_str(v):
    """Conversión a cadena con las reglas de JS (`String(v)`)."""
    if v is UNDEFINED:
        return 'undefined'
    if v is NULL:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float):
        if math.isinf(v):
            return 'Infinity' if v > 0 else '-Infinity'
        if math.isnan(v):
            return 'NaN'
        if v == int(v):
            return str(int(v))
        return repr(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return ','.join(js_str(e) for e in v)
    if isinstance(v, (EsJSObject, EsJSFunction, BuiltinFunction)):
        return repr(v)
    return str(v)


def js_bool(v):
    """Conversión a booleano con las reglas de "truthiness" de JS."""
    if v is UNDEFINED or v is NULL:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0 and not math.isnan(float(v))
    if isinstance(v, str):
        return len(v) > 0
    return True


def js_num(v):
    """Conversión a número con las reglas de JS (`Number(v)`).

    Las cadenas enteras devuelven `int` y las decimales `float`, igual que
    el lexer; esto mantiene consistente el formateo posterior en js_str.
    """
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            return float('nan')
    if v is NULL:
        return 0
    if v is UNDEFINED:
        return float('nan')
    return float('nan')


def js_add(a, b):
    """Operador `+`: concatena si algún operando es cadena, si no suma."""
    if isinstance(a, str) or isinstance(b, str):
        return js_str(a) + js_str(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a + b
    return js_str(a) + js_str(b)


def _raw_eq(a, b):
    """Igualdad base usada por `==` y `===` una vez resuelto el tipo."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return a is b or a == b


def js_eq(a, b):
    """Igualdad débil `==` (con coerción de tipos)."""
    if type(a) is type(b):
        return _raw_eq(a, b)
    if isinstance(a, bool):
        return js_eq(1 if a else 0, b)
    if isinstance(b, bool):
        return js_eq(a, 1 if b else 0)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, str):
        return a == js_num(b)
    if isinstance(a, str) and isinstance(b, (int, float)):
        return js_num(a) == b
    if (a is NULL or a is UNDEFINED) and (b is NULL or b is UNDEFINED):
        return True
    if a is NULL or a is UNDEFINED or b is NULL or b is UNDEFINED:
        return False
    return _raw_eq(a, b)


def js_strict_eq(a, b):
    """Igualdad estricta `===` (sin coerción)."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if type(a) is not type(b):
        return False
    return _raw_eq(a, b)


def js_exponential(v, digits=None):
    """Notación científica estilo JS: `(12.5).toExponential()` -> '1.25e+1'.

    Sin `digits`: usa los dígitos mínimos necesarios. El exponente lleva
    signo y no tiene ceros a la izquierda.
    """
    v = float(v)
    if math.isnan(v):
        return 'NaN'
    if math.isinf(v):
        return 'Infinity' if v > 0 else '-Infinity'
    if digits is None:
        mant, exp = f'{v:e}'.split('e')
        if '.' in mant:
            mant = mant.rstrip('0').rstrip('.')
    else:
        mant, exp = format(v, f'.{int(digits)}e').split('e')
    sign = '-' if exp[0] == '-' else '+'
    return f'{mant}e{sign}{int(exp)}'


# ═══════════════════════════════════════════════════════════════════════
# 5. TOKENS
# ═══════════════════════════════════════════════════════════════════════

T_NUMBER = 'NUMBER'
T_STRING = 'STRING'
T_IDENT = 'IDENT'

T_PLUS = 'PLUS'
T_MINUS = 'MINUS'
T_STAR = 'STAR'
T_SLASH = 'SLASH'
T_PERCENT = 'PERCENT'
T_STARSTAR = 'STARSTAR'

T_EQ = 'EQ'
T_PLUSEQ = 'PLUSEQ'
T_MINUSEQ = 'MINUSEQ'
T_STAREQ = 'STAREQ'
T_SLASHEQ = 'SLASHEQ'
T_PERCENTEQ = 'PERCENTEQ'

T_EQEQ = 'EQEQ'
T_BANGEQ = 'BANGEQ'
T_EQEQEQ = 'EQEQEQ'
T_BANGEQEQ = 'BANGEQEQ'

T_LT = 'LT'
T_GT = 'GT'
T_LTEQ = 'LTEQ'
T_GTEQ = 'GTEQ'

T_AMPAMP = 'AMPAMP'
T_PIPEPIPE = 'PIPEPIPE'
T_BANG = 'BANG'

T_PLUSPLUS = 'PLUSPLUS'
T_MINUSMINUS = 'MINUSMINUS'

T_ARROW = 'ARROW'
T_QUESTION = 'QUESTION'

T_LPAREN = 'LPAREN'
T_RPAREN = 'RPAREN'
T_LBRACE = 'LBRACE'
T_RBRACE = 'RBRACE'
T_LBRACKET = 'LBRACKET'
T_RBRACKET = 'RBRACKET'

T_SEMI = 'SEMI'
T_COLON = 'COLON'
T_COMMA = 'COMMA'
T_DOT = 'DOT'
T_EOF = 'EOF'


class Token:
    """Unidad léxica: tipo, valor literal (o None) y línea de origen."""

    __slots__ = ('type', 'value', 'line')

    def __init__(self, t, v, l=0):
        self.type = t
        self.value = v
        self.line = l

    def __repr__(self):
        return f'T({self.type},{self.value!r})'


# ═══════════════════════════════════════════════════════════════════════
# 6. LEXER
# ═══════════════════════════════════════════════════════════════════════

class Lexer:
    """Convierte el texto fuente en una lista de Tokens."""

    def __init__(self, src):
        self.src = src
        self.pos = 0
        self.line = 1

    # ── utilidades de cursor ───────────────────────────────────────────
    def _pk(self, o=0):
        """Mira el carácter en pos+o sin consumirlo ('\\0' si EOF)."""
        p = self.pos + o
        return self.src[p] if p < len(self.src) else '\0'

    def _adv(self):
        """Consume y devuelve el carácter actual, contando saltos de línea."""
        c = self.src[self.pos]
        self.pos += 1
        if c == '\n':
            self.line += 1
        return c

    def _match(self, c):
        """Consume el carácter `c` si coincide; devuelve si hubo match."""
        if self.pos < len(self.src) and self.src[self.pos] == c:
            self.pos += 1
            return True
        return False

    # ── tramos a ignorar / literales ───────────────────────────────────
    def _skip(self):
        """Salta espacios y comentarios `//` y `/* */`."""
        while self.pos < len(self.src):
            c = self.src[self.pos]
            if c in ' \t\r\n':
                self._adv()
            elif c == '/' and self._pk(1) == '/':
                while self.pos < len(self.src) and self.src[self.pos] != '\n':
                    self.pos += 1
            elif c == '/' and self._pk(1) == '*':
                self.pos += 2
                while self.pos < len(self.src):
                    if self.src[self.pos] == '*' and self._pk(1) == '/':
                        self.pos += 2
                        break
                    if self.src[self.pos] == '\n':
                        self.line += 1
                    self.pos += 1
            else:
                break

    def _str(self, q):
        """Lee un literal de cadena delimitado por la comilla `q`."""
        self.pos += 1
        buf = []
        escapes = {'n': '\n', 't': '\t', 'r': '\r',
                   '"': '"', "'": "'", '\\': '\\'}
        while self.pos < len(self.src):
            c = self.src[self.pos]
            if c == '\\':
                self.pos += 1
                e = self.src[self.pos] if self.pos < len(self.src) else ''
                buf.append(escapes.get(e, e))
                self.pos += 1
            elif c == q:
                self.pos += 1
                break
            else:
                if c == '\n':
                    self.line += 1
                buf.append(c)
                self.pos += 1
        return ''.join(buf)

    def _num(self):
        """Lee un literal numérico (entero, decimal, exponente o hex)."""
        s = self.pos
        # hexadecimal: 0x...
        if self._pk() == '0' and self._pk(1) in ('x', 'X'):
            self.pos += 2
            while (self.pos < len(self.src)
                   and self.src[self.pos] in '0123456789abcdefABCDEF'):
                self.pos += 1
            return int(self.src[s:self.pos], 16)
        # parte entera
        while self.pos < len(self.src) and self.src[self.pos].isdigit():
            self.pos += 1
        flt = False
        # parte decimal
        if (self.pos < len(self.src) and self.src[self.pos] == '.'
                and self.pos + 1 < len(self.src)
                and self.src[self.pos + 1].isdigit()):
            flt = True
            self.pos += 1
            while self.pos < len(self.src) and self.src[self.pos].isdigit():
                self.pos += 1
        # exponente
        if self.pos < len(self.src) and self.src[self.pos] in ('e', 'E'):
            flt = True
            self.pos += 1
            if self.pos < len(self.src) and self.src[self.pos] in ('+', '-'):
                self.pos += 1
            while self.pos < len(self.src) and self.src[self.pos].isdigit():
                self.pos += 1
        t = self.src[s:self.pos]
        return float(t) if flt else int(t)

    def _is_id(self, c):
        """¿`c` puede formar parte de un identificador?"""
        return c == '_' or c.isalpha() or c.isdigit()

    # ── bucle principal ────────────────────────────────────────────────
    def tokenize(self):
        """Devuelve la lista completa de tokens, terminada en T_EOF."""
        toks = []
        while True:
            self._skip()
            if self.pos >= len(self.src):
                toks.append(Token(T_EOF, None, self.line))
                break
            ln = self.line
            c = self.src[self.pos]

            # literales y nombres
            if c in ('"', "'"):
                toks.append(Token(T_STRING, self._str(c), ln))
                continue
            if c.isdigit() or (c == '.' and self.pos + 1 < len(self.src)
                               and self.src[self.pos + 1].isdigit()):
                toks.append(Token(T_NUMBER, self._num(), ln))
                continue
            if c == '_' or c.isalpha():
                s = self.pos
                while (self.pos < len(self.src)
                       and self._is_id(self.src[self.pos])):
                    self.pos += 1
                toks.append(Token(T_IDENT, self.src[s:self.pos], ln))
                continue

            # operadores y signos de puntuación
            self.pos += 1
            if c == '=':
                if self._match('='):
                    toks.append(Token(
                        T_EQEQEQ if self._match('=') else T_EQEQ, None, ln))
                elif self._match('>'):
                    toks.append(Token(T_ARROW, None, ln))
                else:
                    toks.append(Token(T_EQ, None, ln))
            elif c == '!':
                if self._match('='):
                    toks.append(Token(
                        T_BANGEQEQ if self._match('=') else T_BANGEQ, None, ln))
                else:
                    toks.append(Token(T_BANG, None, ln))
            elif c == '<':
                toks.append(Token(
                    T_LTEQ if self._match('=') else T_LT, None, ln))
            elif c == '>':
                toks.append(Token(
                    T_GTEQ if self._match('=') else T_GT, None, ln))
            elif c == '+':
                if self._match('+'):
                    toks.append(Token(T_PLUSPLUS, None, ln))
                elif self._match('='):
                    toks.append(Token(T_PLUSEQ, None, ln))
                else:
                    toks.append(Token(T_PLUS, None, ln))
            elif c == '-':
                if self._match('-'):
                    toks.append(Token(T_MINUSMINUS, None, ln))
                elif self._match('='):
                    toks.append(Token(T_MINUSEQ, None, ln))
                else:
                    toks.append(Token(T_MINUS, None, ln))
            elif c == '*':
                if self._match('*'):
                    toks.append(Token(T_STARSTAR, None, ln))
                elif self._match('='):
                    toks.append(Token(T_STAREQ, None, ln))
                else:
                    toks.append(Token(T_STAR, None, ln))
            elif c == '/':
                toks.append(Token(
                    T_SLASHEQ if self._match('=') else T_SLASH, None, ln))
            elif c == '%':
                toks.append(Token(
                    T_PERCENTEQ if self._match('=') else T_PERCENT, None, ln))
            elif c == '&' and self._match('&'):
                toks.append(Token(T_AMPAMP, None, ln))
            elif c == '|' and self._match('|'):
                toks.append(Token(T_PIPEPIPE, None, ln))
            elif c == '(':
                toks.append(Token(T_LPAREN, None, ln))
            elif c == ')':
                toks.append(Token(T_RPAREN, None, ln))
            elif c == '{':
                toks.append(Token(T_LBRACE, None, ln))
            elif c == '}':
                toks.append(Token(T_RBRACE, None, ln))
            elif c == '[':
                toks.append(Token(T_LBRACKET, None, ln))
            elif c == ']':
                toks.append(Token(T_RBRACKET, None, ln))
            elif c == ';':
                toks.append(Token(T_SEMI, None, ln))
            elif c == ':':
                toks.append(Token(T_COLON, None, ln))
            elif c == ',':
                toks.append(Token(T_COMMA, None, ln))
            elif c == '.':
                toks.append(Token(T_DOT, None, ln))
            elif c == '?':
                toks.append(Token(T_QUESTION, None, ln))
        return toks


# ═══════════════════════════════════════════════════════════════════════
# 7. NODOS DEL AST
# ═══════════════════════════════════════════════════════════════════════
# El nombre de cada clase determina el método visitor (`v_<NombreClase>`),
# por lo que NO deben renombrarse sin actualizar el intérprete.

class Node:
    """Clase base de todos los nodos del árbol de sintaxis."""


# ── sentencias ─────────────────────────────────────────────────────────

class Program(Node):
    def __init__(self, body):
        self.body = body


class Block(Node):
    def __init__(self, body):
        self.body = body


class VarDecl(Node):
    def __init__(self, kind, name, value, line=0):
        self.kind = kind          # 'let' | 'const' | 'var'
        self.name = name
        self.value = value
        self.line = line


class ExprStmt(Node):
    def __init__(self, expr, line=0):
        self.expr = expr
        self.line = line


class IfStmt(Node):
    def __init__(self, test, cons, alt, line=0):
        self.test = test
        self.cons = cons
        self.alt = alt
        self.line = line


class WhileStmt(Node):
    def __init__(self, test, body, line=0):
        self.test = test
        self.body = body
        self.line = line


class ForStmt(Node):
    def __init__(self, init, test, update, body, line=0):
        self.init = init
        self.test = test
        self.update = update
        self.body = body
        self.line = line


class SwitchStmt(Node):
    def __init__(self, disc, cases, line=0):
        self.disc = disc
        self.cases = cases
        self.line = line


class SwitchCase(Node):
    def __init__(self, test, body):
        self.test = test          # None == porDefecto
        self.body = body


class FuncDecl(Node):
    def __init__(self, name, params, body, line=0):
        self.name = name
        self.params = params
        self.body = body
        self.line = line


class ReturnStmt(Node):
    def __init__(self, value, line=0):
        self.value = value
        self.line = line


class BreakStmt(Node):
    def __init__(self, line=0):
        self.line = line


class ContinueStmt(Node):
    def __init__(self, line=0):
        self.line = line


# ── expresiones ────────────────────────────────────────────────────────

class NumLit(Node):
    def __init__(self, v):
        self.v = v


class StrLit(Node):
    def __init__(self, v):
        self.v = v


class BoolLit(Node):
    def __init__(self, v):
        self.v = v


class NullLit(Node):
    pass


class UndefLit(Node):
    pass


class InfLit(Node):
    pass


class Ident(Node):
    def __init__(self, name, line=0):
        self.name = name
        self.line = line


class BinOp(Node):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right


class LogOp(Node):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right


class UnaryOp(Node):
    def __init__(self, op, expr, prefix=True):
        self.op = op
        self.expr = expr
        self.prefix = prefix


class Assign(Node):
    def __init__(self, target, op, value, line=0):
        self.target = target
        self.op = op
        self.value = value
        self.line = line


class Member(Node):
    def __init__(self, obj, prop, computed=False):
        self.obj = obj
        self.prop = prop
        self.computed = computed   # True == acceso por corchetes


class Call(Node):
    def __init__(self, callee, args, line=0):
        self.callee = callee
        self.args = args
        self.line = line


class ObjLit(Node):
    def __init__(self, props):
        self.props = props         # lista de (clave, nodo_valor, es_metodo)


class ArrLit(Node):
    def __init__(self, elems):
        self.elems = elems


class Arrow(Node):
    def __init__(self, params, body):
        self.params = params
        self.body = body


class Ternary(Node):
    def __init__(self, test, cons, alt):
        self.test = test
        self.cons = cons
        self.alt = alt


# ═══════════════════════════════════════════════════════════════════════
# 8. PARSER (descenso recursivo con precedencia)
# ═══════════════════════════════════════════════════════════════════════
# Cascada de precedencia de expresiones (de menor a mayor prioridad):
#   _assign → _ternary → _or → _and → _eq → _cmp → _add → _mul
#           → _exp_ → _unary → _postfix → _primary

class Parser:
    """Construye el AST a partir de la lista de tokens."""

    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    # ── utilidades de cursor ───────────────────────────────────────────
    def _c(self):
        """Token actual."""
        return self.toks[self.pos]

    def _pk(self, o=1):
        """Token en pos+o (o el último, EOF, si se pasa del final)."""
        p = self.pos + o
        return self.toks[p] if p < len(self.toks) else self.toks[-1]

    def _adv(self):
        """Consume y devuelve el token actual."""
        t = self.toks[self.pos]
        if self.pos < len(self.toks) - 1:
            self.pos += 1
        return t

    def _exp(self, tt, v=None):
        """Exige un token de tipo `tt` (y valor `v`); error si no aparece."""
        t = self._c()
        if t.type != tt:
            raise SyntaxError(
                f"L{t.line}: esperaba {tt!r} encontré {t.type!r}({t.value!r})")
        if v is not None and t.value != v:
            raise SyntaxError(f"L{t.line}: esperaba {v!r}")
        return self._adv()

    def _match(self, tt, v=None):
        """Consume el token si coincide con `tt`/`v`; si no devuelve None."""
        t = self._c()
        if t.type == tt and (v is None or t.value == v):
            return self._adv()
        return None

    def _kw(self, *words):
        """¿El token actual es un identificador en `words` (palabra clave)?"""
        t = self._c()
        return t.type == T_IDENT and t.value in words

    # ── programa y sentencias ──────────────────────────────────────────
    def parse(self):
        body = []
        while self._c().type != T_EOF:
            s = self._stmt()
            if s:
                body.append(s)
        return Program(body)

    def _block(self):
        self._exp(T_LBRACE)
        body = []
        while self._c().type not in (T_RBRACE, T_EOF):
            s = self._stmt()
            if s:
                body.append(s)
        self._exp(T_RBRACE)
        return Block(body)

    def _stmt(self):
        t = self._c()
        if t.type == T_SEMI:
            self._adv()
            return None
        if t.type == T_IDENT:
            v = t.value
            if v in ('mut', 'const', 'var'):
                return self._var_decl()
            if v == 'funcion':
                return self._func_decl()
            if v == 'retornar':
                return self._return()
            if v == 'romper':
                self._adv()
                self._match(T_SEMI)
                return BreakStmt(t.line)
            if v == 'continuar':
                self._adv()
                self._match(T_SEMI)
                return ContinueStmt(t.line)
            if v == 'si':
                return self._if()
            if v == 'mientras':
                return self._while()
            if v == 'para':
                return self._for()
            if v == 'elegir':
                return self._switch()
        if t.type == T_LBRACE:
            return self._block()
        return self._expr_stmt()

    def _var_decl(self, no_semi=False):
        # Soporta declaración múltiple:  mut a = 1, b = 2, c;
        km = {'mut': 'let', 'const': 'const', 'var': 'var'}
        t = self._adv()
        kind = km[t.value]
        line = t.line
        decls = []
        while True:
            name = self._exp(T_IDENT).value
            val = None
            if self._match(T_EQ):
                val = self._assign()   # no _expr(): la coma separa declaradores
            decls.append(VarDecl(kind, name, val, line))
            if not self._match(T_COMMA):
                break
        if not no_semi:
            self._match(T_SEMI)
        # Un solo declarador → mismo nodo de antes (comportamiento idéntico).
        return decls[0] if len(decls) == 1 else Block(decls)

    def _func_decl(self):
        line = self._c().line
        self._adv()
        name = self._exp(T_IDENT).value
        params = self._params()
        body = self._block()
        return FuncDecl(name, params, body, line)

    def _params(self):
        self._exp(T_LPAREN)
        p = []
        while self._c().type != T_RPAREN and self._c().type != T_EOF:
            p.append(self._exp(T_IDENT).value)
            if not self._match(T_COMMA):
                break
        self._exp(T_RPAREN)
        return p

    def _return(self):
        line = self._c().line
        self._adv()
        val = None
        if self._c().type not in (T_SEMI, T_RBRACE, T_EOF):
            val = self._expr()
        self._match(T_SEMI)
        return ReturnStmt(val, line)

    def _if(self):
        line = self._c().line
        self._adv()
        self._exp(T_LPAREN)
        test = self._expr()
        self._exp(T_RPAREN)
        cons = self._block()
        alt = None
        if self._kw('sino'):
            self._adv()
            alt = self._if() if self._kw('si') else self._block()
        return IfStmt(test, cons, alt, line)

    def _while(self):
        line = self._c().line
        self._adv()
        self._exp(T_LPAREN)
        test = self._expr()
        self._exp(T_RPAREN)
        return WhileStmt(test, self._block(), line)

    def _for(self):
        line = self._c().line
        self._adv()
        self._exp(T_LPAREN)
        init = None
        if self._c().type != T_SEMI:
            if self._kw('mut', 'const', 'var'):
                init = self._var_decl(no_semi=True)
            else:
                init = self._expr()
        self._exp(T_SEMI)
        test = None
        if self._c().type != T_SEMI:
            test = self._expr()
        self._exp(T_SEMI)
        upd = None
        if self._c().type != T_RPAREN:
            upd = self._expr()
        self._exp(T_RPAREN)
        return ForStmt(init, test, upd, self._block(), line)

    def _switch(self):
        line = self._c().line
        self._adv()
        self._exp(T_LPAREN)
        disc = self._expr()
        self._exp(T_RPAREN)
        self._exp(T_LBRACE)
        cases = []
        while self._c().type not in (T_RBRACE, T_EOF):
            if self._kw('caso'):
                self._adv()
                tst = self._expr()
                self._exp(T_COLON)
                cases.append(SwitchCase(tst, self._case_body()))
            elif self._kw('porDefecto'):
                self._adv()
                self._exp(T_COLON)
                cases.append(SwitchCase(None, self._case_body()))
            else:
                break
        self._exp(T_RBRACE)
        return SwitchStmt(disc, cases, line)

    def _case_body(self):
        body = []
        while (self._c().type not in (T_RBRACE, T_EOF)
               and not self._kw('caso', 'porDefecto')):
            s = self._stmt()
            if s:
                body.append(s)
        return body

    def _expr_stmt(self):
        line = self._c().line
        e = self._expr()
        self._match(T_SEMI)
        return ExprStmt(e, line)

    # ── expresiones (cascada de precedencia) ───────────────────────────
    def _expr(self):
        return self._assign()

    def _assign(self):
        left = self._ternary()
        ops = {T_EQ: '=', T_PLUSEQ: '+=', T_MINUSEQ: '-=',
               T_STAREQ: '*=', T_SLASHEQ: '/=', T_PERCENTEQ: '%='}
        if self._c().type in ops:
            op = ops[self._adv().type]
            val = self._assign()
            return Assign(left, op, val)
        return left

    def _ternary(self):
        c = self._or()
        if self._match(T_QUESTION):
            # brazos en _assign → asociatividad derecha (a ? b : c ? d : e)
            t = self._assign()
            self._exp(T_COLON)
            a = self._assign()
            return Ternary(c, t, a)
        return c

    def _or(self):
        l = self._and()
        while self._c().type == T_PIPEPIPE:
            self._adv()
            l = LogOp(l, '||', self._and())
        return l

    def _and(self):
        l = self._eq()
        while self._c().type == T_AMPAMP:
            self._adv()
            l = LogOp(l, '&&', self._eq())
        return l

    def _eq(self):
        l = self._cmp()
        mp = {T_EQEQ: '==', T_BANGEQ: '!=',
              T_EQEQEQ: '===', T_BANGEQEQ: '!=='}
        while self._c().type in mp:
            op = mp[self._adv().type]
            l = BinOp(l, op, self._cmp())
        return l

    def _cmp(self):
        l = self._add()
        mp = {T_LT: '<', T_GT: '>', T_LTEQ: '<=', T_GTEQ: '>='}
        while self._c().type in mp:
            op = mp[self._adv().type]
            l = BinOp(l, op, self._add())
        return l

    def _add(self):
        l = self._mul()
        while self._c().type in (T_PLUS, T_MINUS):
            op = '+' if self._adv().type == T_PLUS else '-'
            l = BinOp(l, op, self._mul())
        return l

    def _mul(self):
        l = self._exp_()
        mp = {T_STAR: '*', T_SLASH: '/', T_PERCENT: '%'}
        while self._c().type in mp:
            op = mp[self._adv().type]
            l = BinOp(l, op, self._exp_())
        return l

    def _exp_(self):
        b = self._unary()
        if self._c().type == T_STARSTAR:
            self._adv()
            return BinOp(b, '**', self._unary())
        return b

    def _unary(self):
        if self._c().type == T_BANG:
            self._adv()
            return UnaryOp('!', self._unary())
        if self._c().type == T_MINUS:
            self._adv()
            return UnaryOp('-', self._unary())
        if self._c().type == T_PLUS:
            self._adv()
            return UnaryOp('+', self._unary())
        if self._c().type == T_PLUSPLUS:
            self._adv()
            return UnaryOp('++', self._postfix(), True)
        if self._c().type == T_MINUSMINUS:
            self._adv()
            return UnaryOp('--', self._postfix(), True)
        return self._postfix()

    def _postfix(self):
        e = self._primary()
        while True:
            if self._c().type == T_DOT:
                self._adv()
                prop = self._exp(T_IDENT).value
                e = Member(e, prop, False)
            elif self._c().type == T_LBRACKET:
                self._adv()
                prop = self._expr()
                self._exp(T_RBRACKET)
                e = Member(e, prop, True)
            elif self._c().type == T_LPAREN:
                ln = self._c().line
                self._adv()
                args = []
                while (self._c().type != T_RPAREN
                       and self._c().type != T_EOF):
                    args.append(self._expr())
                    if not self._match(T_COMMA):
                        break
                self._exp(T_RPAREN)
                e = Call(e, args, ln)
            elif self._c().type == T_PLUSPLUS:
                self._adv()
                e = UnaryOp('++', e, False)
            elif self._c().type == T_MINUSMINUS:
                self._adv()
                e = UnaryOp('--', e, False)
            else:
                break
        return e

    def _primary(self):
        t = self._c()
        if t.type == T_NUMBER:
            self._adv()
            return NumLit(t.value)
        if t.type == T_STRING:
            self._adv()
            return StrLit(t.value)

        if t.type == T_IDENT:
            kw = t.value
            if kw == 'verdadero':
                self._adv()
                return BoolLit(True)
            if kw == 'falso':
                self._adv()
                return BoolLit(False)
            if kw == 'nulo':
                self._adv()
                return NullLit()
            if kw == 'indefinido':
                self._adv()
                return UndefLit()
            if kw == 'Infinito':
                self._adv()
                return InfLit()
            if kw == 'funcion':
                return self._func_expr()
            self._adv()
            # `id => cuerpo` (flecha de un parámetro sin paréntesis)
            if self._c().type == T_ARROW:
                self._adv()
                return Arrow([kw], self._arrow_body())
            return Ident(t.value, t.line)

        if t.type == T_LPAREN:
            self._adv()
            # `() =>`
            if self._c().type == T_RPAREN:
                self._adv()
                if self._c().type == T_ARROW:
                    self._adv()
                    return Arrow([], self._arrow_body())
                return NullLit()
            # intentar `(params) =>`; si no, expresión entre paréntesis
            saved = self.pos
            try:
                ps = self._try_arrow_params()
                if self._c().type == T_ARROW:
                    self._adv()
                    return Arrow(ps, self._arrow_body())
                self.pos = saved
            except SyntaxError:
                self.pos = saved
            e = self._expr()
            self._exp(T_RPAREN)
            return e

        if t.type == T_LBRACE:
            return self._obj_lit()

        if t.type == T_LBRACKET:
            self._adv()
            elems = []
            while (self._c().type != T_RBRACKET
                   and self._c().type != T_EOF):
                elems.append(self._expr())
                if not self._match(T_COMMA):
                    break
            self._exp(T_RBRACKET)
            return ArrLit(elems)

        # token inesperado: tolerado como nulo (la entrada no trae errores)
        self._adv()
        return NullLit()

    def _try_arrow_params(self):
        ps = []
        while self._c().type != T_RPAREN and self._c().type != T_EOF:
            if self._c().type != T_IDENT:
                raise SyntaxError('no arrow')
            ps.append(self._adv().value)
            if not self._match(T_COMMA):
                break
        self._exp(T_RPAREN)
        return ps

    def _arrow_body(self):
        if self._c().type == T_LBRACE:
            return self._block()
        return self._assign()

    def _func_expr(self):
        self._adv()
        name = None
        if self._c().type == T_IDENT:
            name = self._adv().value
        ps = self._params()
        body = self._block()
        fn = Arrow(ps, body)
        fn._name = name
        return fn

    def _obj_lit(self):
        self._adv()
        props = []
        while self._c().type != T_RBRACE and self._c().type != T_EOF:
            t = self._c()
            if t.type == T_STRING:
                key = self._adv().value
            elif t.type in (T_IDENT, T_NUMBER):
                key = str(self._adv().value)
            else:
                break
            if self._c().type == T_LPAREN:
                # método abreviado: clave(params) { ... }
                ps = self._params()
                body = self._block()
                props.append((key, Arrow(ps, body), True))
            else:
                self._exp(T_COLON)
                val = self._expr()
                props.append((key, val, False))
            self._match(T_COMMA)
        self._exp(T_RBRACE)
        return ObjLit(props)


# ═══════════════════════════════════════════════════════════════════════
# 9. ENTORNO (tabla de símbolos encadenada)
# ═══════════════════════════════════════════════════════════════════════

class Env:
    """Ámbito de variables enlazado a su ámbito padre (closure léxico)."""

    def __init__(self, parent=None):
        self.v = {}
        self.parent = parent

    def define(self, name, val):
        """Declara/redefine `name` en este ámbito."""
        self.v[name] = val

    def get(self, name):
        """Busca `name` subiendo por la cadena de ámbitos."""
        if name in self.v:
            return self.v[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(name)

    def assign(self, name, val):
        """Asigna a `name` en el ámbito donde esté declarado."""
        if name in self.v:
            self.v[name] = val
            return
        if self.parent:
            self.parent.assign(name, val)
            return
        raise NameError(name)


# ═══════════════════════════════════════════════════════════════════════
# 10. INTÉRPRETE (visitor)
# ═══════════════════════════════════════════════════════════════════════

class Interpreter:
    """Recorre el AST y lo ejecuta.

    Despacho: `V(node, env, this)` llama a `v_<NombreClaseNodo>`. Si no
    existe el método, `_noop` devuelve UNDEFINED (por eso varios errores
    semánticos no rompen, sino que producen `undefined`).
    """

    def __init__(self):
        self.genv = Env()
        self._setup(self.genv)

    # ── globales precargados ───────────────────────────────────────────
    def _setup(self, env):
        """Registra `consola`, `Mate`, `Numero` y `ambiente`."""
        import random as _rand

        # consola.escribir/log/info imprimen a stdout.
        _pr = lambda a, t: print(*[js_str(x) for x in a]) or UNDEFINED
        # consola.error/advertir también van a stdout (no stderr) para que
        # la salida combinada conserve el orden, igual que el editor EsJS.
        _er = _pr
        consola = EsJSObject({
            'escribir': BuiltinFunction('escribir', _pr),
            'log':      BuiltinFunction('log',      _pr),
            'error':    BuiltinFunction('error',    _er),
            'limpiar':  BuiltinFunction('limpiar',  lambda a, t: UNDEFINED),
            'clear':    BuiltinFunction('clear',    lambda a, t: UNDEFINED),
            'info':     BuiltinFunction('info',     _pr),
            'advertir': BuiltinFunction('advertir', _er),
            'warn':     BuiltinFunction('warn',     _er),
        })
        env.define('consola', consola)

        # Mate: constantes y funciones matemáticas (nombres EsJS + alias JS).
        mate = EsJSObject({
            'PI': math.pi, 'E': math.e,
            'LN2': math.log(2), 'LN10': math.log(10),
            'LOG2E': math.log2(math.e), 'LOG10E': math.log10(math.e),
            'SQRT2': math.sqrt(2),
            'abs':       BuiltinFunction('abs',       lambda a, t: abs(js_num(a[0]))),
            'max':       BuiltinFunction('max',       lambda a, t: max(js_num(x) for x in a)),
            'min':       BuiltinFunction('min',       lambda a, t: min(js_num(x) for x in a)),
            'aleatorio': BuiltinFunction('aleatorio', lambda a, t: _rand.random()),
            'piso':      BuiltinFunction('piso',      lambda a, t: math.floor(js_num(a[0]))),
            'floor':     BuiltinFunction('floor',     lambda a, t: math.floor(js_num(a[0]))),
            'techo':     BuiltinFunction('techo',     lambda a, t: math.ceil(js_num(a[0]))),
            'ceil':      BuiltinFunction('ceil',      lambda a, t: math.ceil(js_num(a[0]))),
            'redondear': BuiltinFunction('redondear', lambda a, t: round(js_num(a[0]))),
            'round':     BuiltinFunction('round',     lambda a, t: round(js_num(a[0]))),
            'potencia':  BuiltinFunction('potencia',  lambda a, t: js_num(a[0]) ** js_num(a[1])),
            'pow':       BuiltinFunction('pow',       lambda a, t: js_num(a[0]) ** js_num(a[1])),
            'raiz':      BuiltinFunction('raiz',      lambda a, t: math.sqrt(max(0, js_num(a[0])))),
            'sqrt':      BuiltinFunction('sqrt',      lambda a, t: math.sqrt(max(0, js_num(a[0])))),
            'log':       BuiltinFunction('log',       lambda a, t: math.log(js_num(a[0]))),
            'sin':       BuiltinFunction('sin',       lambda a, t: math.sin(js_num(a[0]))),
            'cos':       BuiltinFunction('cos',       lambda a, t: math.cos(js_num(a[0]))),
            'tan':       BuiltinFunction('tan',       lambda a, t: math.tan(js_num(a[0]))),
            'random':    BuiltinFunction('random',    lambda a, t: _rand.random()),
        })
        env.define('Mate', mate)

        def _pint(a, t):
            """parseInt / interpretarEntero."""
            if not a:
                return float('nan')
            s = js_str(a[0]).strip()
            base = int(js_num(a[1])) if len(a) > 1 else 10
            try:
                m = _re.match(r'^[+-]?[0-9a-fA-F]+', s)
                return int(m.group(), base) if m else float('nan')
            except (ValueError, TypeError):
                return float('nan')

        def _pfloat(a, t):
            """parseFloat / interpretarDecimal."""
            if not a:
                return float('nan')
            s = js_str(a[0]).strip()
            try:
                return float(s)
            except ValueError:
                return float('nan')

        def _is_safe_int(a, t):
            n = js_num(a[0])
            return float(n).is_integer() and abs(n) <= 9007199254740991

        numero = EsJSObject({
            'POSITIVE_INFINITY': float('inf'),
            'NEGATIVE_INFINITY': float('-inf'),
            'NaN': float('nan'),
            'MAX_SAFE_INTEGER': 9007199254740991,
            # nombres EsJS
            'esFinito':           BuiltinFunction('esFinito',    lambda a, t: math.isfinite(js_num(a[0]))),
            'esEntero':           BuiltinFunction('esEntero',     lambda a, t: float(js_num(a[0])).is_integer()),
            'esEnteroSeguro':     BuiltinFunction('esEnteroSeguro', _is_safe_int),
            'esNaN':              BuiltinFunction('esNaN',        lambda a, t: math.isnan(js_num(a[0]))),
            'interpretarDecimal': BuiltinFunction('interpretarDecimal', _pfloat),
            'interpretarEntero':  BuiltinFunction('interpretarEntero',  _pint),
            # alias JS
            'isFinite':      BuiltinFunction('isFinite',      lambda a, t: math.isfinite(js_num(a[0]))),
            'isInteger':     BuiltinFunction('isInteger',     lambda a, t: float(js_num(a[0])).is_integer()),
            'isSafeInteger': BuiltinFunction('isSafeInteger', _is_safe_int),
            'isNaN':         BuiltinFunction('isNaN',         lambda a, t: math.isnan(js_num(a[0]))),
            'parseFloat':    BuiltinFunction('parseFloat',    _pfloat),
            'parseInt':      BuiltinFunction('parseInt',      _pint),
        })
        env.define('Numero', numero)
        env.define('ambiente', EsJSObject())

    # ── despacho ───────────────────────────────────────────────────────
    def V(self, node, env, this=None):
        return getattr(self, 'v_' + type(node).__name__, self._noop)(
            node, env, this)

    def _noop(self, n, e, t):
        return UNDEFINED

    # ── sentencias ─────────────────────────────────────────────────────
    def v_Program(self, n, env, this):
        self._hoist(n.body, env)
        for s in n.body:
            self.V(s, env, this)

    def v_Block(self, n, env, this):
        self._hoist(n.body, env)
        for s in n.body:
            self.V(s, env, this)

    def _hoist(self, stmts, env):
        """Eleva (hoisting) las funciones declaradas con `funcion`."""
        for s in stmts:
            if isinstance(s, FuncDecl):
                fn = EsJSFunction(s.name, s.params, s.body, env)
                env.define(s.name, fn)

    def v_VarDecl(self, n, env, this):
        val = self.V(n.value, env, this) if n.value else UNDEFINED
        env.define(n.name, val)

    def v_ExprStmt(self, n, env, this):
        self.V(n.expr, env, this)

    def v_IfStmt(self, n, env, this):
        if js_bool(self.V(n.test, env, this)):
            self.V(n.cons, env, this)
        elif n.alt:
            self.V(n.alt, env, this)

    def v_WhileStmt(self, n, env, this):
        while js_bool(self.V(n.test, env, this)):
            try:
                self.V(n.body, env, this)
            except BreakSignal:
                break
            except ContinueSignal:
                continue

    def v_ForStmt(self, n, env, this):
        fe = Env(env)
        if n.init:
            self.V(n.init, fe, this)
        while True:
            if n.test and not js_bool(self.V(n.test, fe, this)):
                break
            try:
                self.V(n.body, fe, this)
            except BreakSignal:
                break
            except ContinueSignal:
                pass
            if n.update:
                self.V(n.update, fe, this)

    def v_SwitchStmt(self, n, env, this):
        disc = self.V(n.disc, env, this)
        matched = False
        try:
            for case in n.cases:
                if not matched:
                    matched = (case.test is None
                               or js_strict_eq(disc,
                                               self.V(case.test, env, this)))
                if matched:
                    for s in case.body:
                        self.V(s, env, this)
        except BreakSignal:
            pass

    def v_FuncDecl(self, n, env, this):
        pass  # ya fue elevada por _hoist

    def v_ReturnStmt(self, n, env, this):
        raise ReturnSignal(
            self.V(n.value, env, this) if n.value else UNDEFINED)

    def v_BreakStmt(self, n, env, this):
        raise BreakSignal()

    def v_ContinueStmt(self, n, env, this):
        raise ContinueSignal()

    # ── literales ──────────────────────────────────────────────────────
    def v_NumLit(self, n, e, t):
        return n.v

    def v_StrLit(self, n, e, t):
        return n.v

    def v_BoolLit(self, n, e, t):
        return n.v

    def v_NullLit(self, n, e, t):
        return NULL

    def v_UndefLit(self, n, e, t):
        return UNDEFINED

    def v_InfLit(self, n, e, t):
        return float('inf')

    def v_Ident(self, n, env, this):
        if n.name == 'ambiente':
            return this if this is not None else env.get('ambiente')
        try:
            return env.get(n.name)
        except NameError:
            return UNDEFINED

    # ── operadores ─────────────────────────────────────────────────────
    def v_BinOp(self, n, env, this):
        L = self.V(n.left, env, this)
        R = self.V(n.right, env, this)
        op = n.op
        if op == '+':
            return js_add(L, R)
        if op == '-':
            return js_num(L) - js_num(R)
        if op == '*':
            return js_num(L) * js_num(R)
        if op == '/':
            l = js_num(L)
            r = js_num(R)
            if r == 0:
                if l == 0 or (isinstance(l, float) and math.isnan(l)):
                    return float('nan')
                return float('inf') if l > 0 else float('-inf')
            return l / r
        if op == '%':
            r = js_num(R)
            return js_num(L) % r if r != 0 else float('nan')
        if op == '**':
            return js_num(L) ** js_num(R)
        if op == '==':
            return js_eq(L, R)
        if op == '!=':
            return not js_eq(L, R)
        if op == '===':
            return js_strict_eq(L, R)
        if op == '!==':
            return not js_strict_eq(L, R)
        # comparación relacional: dos cadenas → lexicográfica (como JS);
        # en cualquier otro caso se coacciona a número.
        if isinstance(L, str) and isinstance(R, str):
            if op == '<':
                return L < R
            if op == '>':
                return L > R
            if op == '<=':
                return L <= R
            if op == '>=':
                return L >= R
        nl = js_num(L)
        nr = js_num(R)
        if op == '<':
            return nl < nr
        if op == '>':
            return nl > nr
        if op == '<=':
            return nl <= nr
        if op == '>=':
            return nl >= nr
        return UNDEFINED

    def v_LogOp(self, n, env, this):
        L = self.V(n.left, env, this)
        if n.op == '&&':
            return self.V(n.right, env, this) if js_bool(L) else L
        return L if js_bool(L) else self.V(n.right, env, this)

    def v_UnaryOp(self, n, env, this):
        op = n.op
        prefix = n.prefix
        if op == '!':
            return not js_bool(self.V(n.expr, env, this))
        if op == '-':
            return -js_num(self.V(n.expr, env, this))
        if op == '+':
            return js_num(self.V(n.expr, env, this))
        # incremento/decremento (++ / --)
        delta = 1 if op == '++' else -1
        old = js_num(self.V(n.expr, env, this))
        new = old + delta
        self._set_target(n.expr, new, env, this)
        return new if prefix else old

    def _set_target(self, tgt, val, env, this):
        """Asigna `val` a un destino: identificador o miembro."""
        if isinstance(tgt, Ident):
            if tgt.name == 'ambiente':
                return
            try:
                env.assign(tgt.name, val)
            except NameError:
                env.define(tgt.name, val)
        elif isinstance(tgt, Member):
            obj = self.V(tgt.obj, env, this)
            if (isinstance(tgt.obj, Ident) and tgt.obj.name == 'ambiente'
                    and this is not None):
                obj = this
            key = (tgt.prop if not tgt.computed
                   else js_str(self.V(tgt.prop, env, this)))
            self._set_prop(obj, key, val)

    def v_Assign(self, n, env, this):
        rhs = self.V(n.value, env, this)
        if n.op == '=':
            self._set_target(n.target, rhs, env, this)
            return rhs
        lhs = self.V(n.target, env, this)
        op = n.op[0]
        if op == '+':
            r = js_add(lhs, rhs)
        elif op == '-':
            r = js_num(lhs) - js_num(rhs)
        elif op == '*':
            r = js_num(lhs) * js_num(rhs)
        elif op == '/':
            nl = js_num(lhs)
            d = js_num(rhs)
            if d == 0:
                if nl == 0 or (isinstance(nl, float) and math.isnan(nl)):
                    r = float('nan')
                else:
                    r = float('inf') if nl > 0 else float('-inf')
            else:
                r = nl / d
        elif op == '%':
            d = js_num(rhs)
            r = js_num(lhs) % d if d != 0 else float('nan')
        else:
            r = rhs
        self._set_target(n.target, r, env, this)
        return r

    # ── acceso a propiedades ───────────────────────────────────────────
    def v_Member(self, n, env, this):
        obj = self.V(n.obj, env, this)
        if (isinstance(n.obj, Ident) and n.obj.name == 'ambiente'
                and this is not None):
            obj = this
        key = (n.prop if not n.computed
               else js_str(self.V(n.prop, env, this)))
        return self._get_prop(obj, key)

    def _get_prop(self, obj, key):
        """Lee `obj[key]`, incluyendo "métodos" de listas/cadenas/números.

        No hay prototipos: los métodos se devuelven como BuiltinFunction
        creadas sobre la marcha y cerradas sobre `obj`.
        """
        if isinstance(obj, EsJSObject):
            return obj.get_prop(key)

        if isinstance(obj, list):
            if key in ('longitud', 'length'):
                return len(obj)
            if key in ('agregar', 'push'):
                def _push(a, t):
                    obj.extend(a)
                    return len(obj)
                return BuiltinFunction('push', _push)
            if key == 'pop':
                return BuiltinFunction(
                    'pop', lambda a, t: obj.pop() if obj else UNDEFINED)
            if key in ('unshift',):
                return BuiltinFunction(
                    'unshift',
                    lambda a, t: (obj.insert(0, a[0]), len(obj))[-1])
            if key == 'shift':
                return BuiltinFunction(
                    'shift', lambda a, t: obj.pop(0) if obj else UNDEFINED)
            if key == 'join':
                return BuiltinFunction(
                    'join',
                    lambda a, t: (js_str(a[0]) if a else ',').join(
                        js_str(e) for e in obj))
            if key == 'reverse':
                return BuiltinFunction(
                    'reverse', lambda a, t: (obj.reverse(), obj)[-1])
            if key == 'indexOf':
                return BuiltinFunction(
                    'indexOf',
                    lambda a, t: next(
                        (i for i, v in enumerate(obj)
                         if js_strict_eq(v, a[0])), -1))
            if key == 'includes':
                return BuiltinFunction(
                    'includes',
                    lambda a, t: any(js_strict_eq(v, a[0]) for v in obj))
            try:
                idx = int(key)
                return obj[idx] if 0 <= idx < len(obj) else UNDEFINED
            except (ValueError, TypeError):
                return UNDEFINED

        if isinstance(obj, str):
            if key in ('longitud', 'length'):
                return len(obj)
            if key in ('aCadena', 'toString'):
                return BuiltinFunction('toString', lambda a, t: obj)
            if key == 'toUpperCase':
                return BuiltinFunction('toUpperCase', lambda a, t: obj.upper())
            if key == 'toLowerCase':
                return BuiltinFunction('toLowerCase', lambda a, t: obj.lower())
            if key == 'trim':
                return BuiltinFunction('trim', lambda a, t: obj.strip())
            if key == 'split':
                return BuiltinFunction(
                    'split',
                    lambda a, t: obj.split(js_str(a[0])) if a else list(obj))
            if key == 'includes':
                return BuiltinFunction(
                    'includes',
                    lambda a, t: (js_str(a[0]) in obj) if a else False)
            if key == 'indexOf':
                return BuiltinFunction(
                    'indexOf',
                    lambda a, t: obj.find(js_str(a[0])) if a else -1)
            if key in ('substring', 'slice'):
                def _sl(a, t, o=obj):
                    s = int(js_num(a[0])) if a else 0
                    e = int(js_num(a[1])) if len(a) > 1 else len(o)
                    return o[s:e]
                return BuiltinFunction('slice', _sl)
            return UNDEFINED

        if isinstance(obj, (int, float)):
            v = obj
            if key in ('aExponencial', 'toExponential'):
                return BuiltinFunction(
                    'toExponential',
                    lambda a, t, v=v: js_exponential(
                        v, int(js_num(a[0])) if a else None))
            if key in ('fijarDecimales', 'toFixed'):
                return BuiltinFunction(
                    'toFixed',
                    lambda a, t, v=v: (f'{float(v):.{int(js_num(a[0]))}f}'
                                       if a else f'{float(v):.0f}'))
            if key in ('aCadena', 'toString'):
                return BuiltinFunction(
                    'toString', lambda a, t, v=v: js_str(v))
            if key in ('valorDe', 'valueOf'):
                return BuiltinFunction('valueOf', lambda a, t, v=v: v)
            if key in ('aPrecision', 'toPrecision'):
                return BuiltinFunction(
                    'toPrecision',
                    lambda a, t, v=v: (f'{float(v):.{int(js_num(a[0]))}g}'
                                       if a else str(v)))
            return UNDEFINED

        return UNDEFINED

    def _set_prop(self, obj, key, val):
        """Escribe `obj[key] = val` para objetos y listas."""
        if isinstance(obj, EsJSObject):
            obj.set_prop(key, val)
        elif isinstance(obj, list):
            try:
                idx = int(key)
                while len(obj) <= idx:
                    obj.append(UNDEFINED)
                obj[idx] = val
            except (ValueError, TypeError):
                pass

    # ── llamadas ───────────────────────────────────────────────────────
    def v_Call(self, n, env, this):
        args = [self.V(a, env, this) for a in n.args]
        cn = n.callee
        call_this = None
        if isinstance(cn, Member):
            call_this = self.V(cn.obj, env, this)
            if (isinstance(cn.obj, Ident) and cn.obj.name == 'ambiente'
                    and this is not None):
                call_this = this
            key = (cn.prop if not cn.computed
                   else js_str(self.V(cn.prop, env, this)))
            fn = self._get_prop(call_this, key)
        else:
            fn = self.V(cn, env, this)
        return self._call(fn, args, call_this)

    def _call(self, fn, args, this):
        """Invoca una función nativa o definida por el usuario."""
        if isinstance(fn, BuiltinFunction):
            r = fn.fn(args, this)
            return UNDEFINED if r is None else r
        if isinstance(fn, EsJSFunction):
            fe = Env(fn.closure)
            for i, p in enumerate(fn.params):
                fe.define(p, args[i] if i < len(args) else UNDEFINED)
            # `ambiente` (this) del cuerpo = receptor de la llamada.
            eff = this
            fe.define('ambiente', eff if eff is not None else EsJSObject())
            if isinstance(fn.body, Block):
                self._hoist(fn.body.body, fe)
            try:
                if isinstance(fn.body, Block):
                    self.v_Block(fn.body, fe, eff)
                else:
                    # flecha corta: el cuerpo es una expresión
                    return self.V(fn.body, fe, eff)
                return UNDEFINED
            except ReturnSignal as r:
                return r.value
        return UNDEFINED

    # ── literales compuestos ───────────────────────────────────────────
    def v_ObjLit(self, n, env, this):
        obj = EsJSObject()
        for key, vn, is_method in n.props:
            if is_method:
                fn = EsJSFunction(key, vn.params, vn.body, env,
                                  is_arrow=False)
                obj.set_prop(key, fn)
            else:
                obj.set_prop(key, self.V(vn, env, this))
        return obj

    def v_ArrLit(self, n, env, this):
        return [self.V(e, env, this) for e in n.elems]

    def v_Arrow(self, n, env, this):
        name = getattr(n, '_name', None) or '<arrow>'
        return EsJSFunction(name, n.params, n.body, env, is_arrow=True)

    def v_Ternary(self, n, env, this):
        branch = n.cons if js_bool(self.V(n.test, env, this)) else n.alt
        return self.V(branch, env, this)


# ═══════════════════════════════════════════════════════════════════════
# 11. PUNTO DE ENTRADA
# ═══════════════════════════════════════════════════════════════════════

def main():
    """Lee el programa EsJS de stdin y lo ejecuta."""
    src = sys.stdin.read()
    try:
        toks = Lexer(src).tokenize()
        tree = Parser(toks).parse()
        interp = Interpreter()
        interp.V(tree, interp.genv, None)
    except ReturnSignal:
        pass
    except SystemExit:
        pass
    except Exception as e:
        print(f"Error en tiempo de ejecución: {e}", file=sys.stderr)


if __name__ == '__main__':
    main()
