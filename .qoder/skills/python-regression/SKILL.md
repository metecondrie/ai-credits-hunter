---
name: python-regression
description: Procedimiento para corregir defectos en Python dejándolos cubiertos por pruebas de regresión con unittest y solo biblioteca estándar: reproducir el fallo con evidencia antes de tocar código, arreglo mínimo, casos límite con subTest, pruebas offline sin red ni APIs externas, verificación de que la prueba nueva falla contra el código original y ejecución únicamente de las pruebas relevantes. Usar al arreglar un bug, al endurecer validación o parseo de entradas, o cuando el usuario pida "prueba de regresión", "reproducir el defecto", "cubrirlo con tests", "unittest", "pruebas sin red".
---

# Python Regression

## Overview

Convierte un defecto en una prueba que falla antes del arreglo y pasa después,
sin depender de red, servicios pagos ni bibliotecas de terceros.

## 1. Reproducir antes de modificar

Ningún arreglo sin reproducción observada:

```bash
python -c "from paquete.modulo import fn; print(repr(fn(entrada_problematica)))"
```

- Guardar la salida real como evidencia del comportamiento defectuoso.
- Identificar el punto exacto: `archivo:linea` y expresión responsable.
- Distinguir el síntoma de la causa: una conversión implícita, un orden de
  evaluación o un supuesto sobre el tipo de dato suelen ser la causa real.

Ejemplos de causas frecuentes en validación de datos externos:

- `bool("false")` es `True`: las cadenas no vacías son verdaderas.
- `bool` es subclase de `int`: `isinstance(True, int)` es `True`, pero
  `isinstance(1, bool)` es `False`. Para exigir booleano auténtico, validar con
  `isinstance(valor, bool)`.
- `float` vs `Decimal` al comparar precios; `None` vs `0` vs `""`.

## 2. Arreglo mínimo

- Corregir solo la causa; no reescribir el módulo ni limpiar alrededor.
- Respetar el contrato de errores ya existente del proyecto (por ejemplo,
  levantar `ValueError` si el llamador ya lo captura) en vez de inventar una
  excepción nueva.
- El mensaje de error debe nombrar el campo y el tipo recibido: facilita el
  diagnóstico y permite afirmarlo en una prueba.
- No agregar compatibilidad hacia atrás ni ramas para casos imposibles.

## 3. Escribir la prueba de regresión

Convenciones con `unittest` (biblioteca estándar):

```python
class ParseTestCase(unittest.TestCase):
    def test_campo_invalido_rechazado(self):
        with self.assertRaises(ValueError):
            parse_response(entrada_invalida)

    def test_matriz_de_casos_limite(self):
        for valor in ("false", "true", 0, 1, 1.0, None, [], {}):
            with self.subTest(valor=valor):
                with self.assertRaises(ValueError):
                    parse_response(construir(valor))
```

- Afirmar con precisión: `assertIs(x, False)` en vez de `assertFalse(x)` cuando
  importa la identidad del tipo.
- Cubrir el caso válido positivo **y** el negativo; una prueba que solo rechaza
  puede pasar con una función que rechaza todo.
- Usar `subTest` para matrices de casos límite: cada valor falla por separado.
- Nombrar la prueba por el comportamiento, no por la implementación.

## 4. Casos límite a recorrer

Según el tipo de entrada, verificar al menos:

- **Booleanos**: `true`, `false`, `"false"`, `"true"`, `0`, `1`, `1.0`, `null`,
  `[]`, `{}`, cadena vacía.
- **Texto**: vacío, solo espacios, muy largo (truncado), con saltos de línea,
  con caracteres no ASCII, envuelto en markdown o texto extra.
- **Números**: `0`, negativos, punto flotante, notación científica, excedidos,
  `NaN`/`Infinity` si llegan por JSON.
- **Estructuras**: clave ausente, clave duplicada, tipo de contenedor
  equivocado, anidamiento inesperado, `null` explícito.
- **Rutas de error**: que el fallo se propague como el proyecto espera y no
  interrumpa el proceso principal.

## 5. Pruebas offline, sin APIs externas

- Inyectar dependencias: HTTP, reloj, almacén de credenciales y rutas de base
  deben recibirse por parámetro o sustituirse por dobles de prueba.
- Bases de datos en directorios temporales (`tempfile.TemporaryDirectory`),
  nunca sobre datos reales u operativos.
- Variables de entorno de aislamiento del proyecto (por ejemplo `ACH_OFFLINE=1`)
  cuando existan.
- Credenciales falsas y evidentes (`gsk_test_123456`), nunca reales ni en
  fixtures.
- Si una prueba exige red, es una prueba de conectividad: separarla y marcarla,
  no mezclarla con las deterministas.

## 6. Ejecutar solo lo pertinente

```bash
python -m unittest discover -s tests -p "test_<area>.py" -v
```

- Correr el archivo afectado primero; después, como máximo, las suites offline
  vecinas que puedan verse impactadas.
- No correr la suite completa ni pruebas de integración con red si el cambio es
  local y las lentas no aportan evidencia.
- Reportar cifras reales: pruebas ejecutadas, pasadas, fallidas y duración.

## 7. Comprobar que la prueba es de regresión

Verificar que las pruebas nuevas **fallan** contra el código original, sin poner
en riesgo el trabajo propio:

```bash
mkdir -p /tmp/base && git archive HEAD | tar -x -C /tmp/base
cp tests/test_<area>.py /tmp/base/tests/
cd /tmp/base && python -m unittest discover -s tests -p "test_<area>.py"
```

`git archive` exporta el commit base a un directorio aparte: no modifica la
rama de trabajo ni requiere `git stash` ni `git checkout --`. Si la prueba pasa
contra el código original, no cubre el defecto: rehacerla.

## 8. Cierre

Informar: defecto reproducido (con la salida observada), causa, cambio
(`archivo:linea`), pruebas agregadas, resultado antes y después, y qué no se
probó. Limpiar los directorios temporales propios.
