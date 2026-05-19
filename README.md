# Universidad Nacional de Colombia

**Facultad de Ingeniería** · Lenguajes de Programación · 2026-1

**Práctica 3 — Intérprete de EsJS**

#### Integrantes

- John Jairo Páez Albino - jopaeza@unal.edu.co 
- Juan Diego Mendoza Torres - jmendozat@unal.edu.co


---

# Intérprete EsJS

Intérprete de EsJS escrito en Python 3.

## Requisitos

- Python 3 (solo librería estándar, sin dependencias externas).

## Cómo ejecutar

```bash
python3 main.py < 01.in.txt
```

## Casos de prueba y salidas esperadas

Los 6 archivos `0N.in.txt` están en la raíz del repo. Salida esperada de cada uno:

### Test 01 — `01.in.txt`

```
Hola Mundo
3.1416
mi cadena
alfabeto
Mayor de edad
```

### Test 02 — `02.in.txt`

```
Martes
0
1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
```

### Test 03 — `03.in.txt`

```
1
2
3
4
30
98.1
128.1
x && y: false
x || y: true
!x: false
!!x: true
Here working
j > 10: true
j < 10: false
j >= 30: true
j <= 29: false
k > j: true
k == j: false
k != j: true
30 == '30': true
30 === '30': false
a: null
b: undefined
c es infinito: true
a === b: false
a == b: true
(j > 10 && k > 50): true
(j < 10 || k > 50): true
!(j > k): true
verdadero == 1: true
falso == 0: true
nulo == indefinido: true
nulo === indefinido: false
```

### Test 04 — `04.in.txt`

```
esFinito: true
esEntero: true
esEnteroSeguro: true
interpretarDecimal: 3.14
interpretarEntero: 10
exponencial: 1.25e+1
decimales: 12.500
cadena: 12.5
valor: 12.5
PI: 3.141592653589793
E: 2.718281828459045
LN2: 0.6931471805599453
LN10: 2.302585092994046
LOG2E: 1.4426950408889634
LOG10E: 0.4342944819032518
true
false
true
false
3.14
20
7
```

### Test 05 — `05.in.txt`

```
Libro agregado: 1984
Libro agregado: El Principito
Libro agregado: Don Quijote
Listado de libros:
- 1984 (George Orwell)
- El Principito (Antoine de Saint-Exupéry)
- Don Quijote (Miguel de Cervantes)
Libro encontrado: 1984
Libro prestado: 1984
El libro no está disponible
Libro devuelto: 1984
1984
George Orwell
```

### Test 06 — `06.in.txt`

```
Hola desde hoisting
undefined
Hola mundo
Usuario aún no definido
Carlos
```

