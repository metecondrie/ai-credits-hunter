---
name: safe-change
description: Procedimiento de cambio protegido y reversible antes de modificar archivos de un repositorio existente: comprobar estado de Git, preservar cambios ajenos en curso, identificar rutas y archivos protegidos, respaldar con verificación y documentar la reversión. Usar antes de editar código o configuración en un repositorio que ya tiene historia o trabajo en curso, al retomar trabajo de otra persona o de otro agente, o cuando el usuario pida "cambio seguro", "sin romper nada", "respaldo antes de tocar", "que sea reversible", "no perder lo que ya está".
---

# Safe Change

## Overview

Garantiza que una modificación sea trazable y reversible: estado previo
conocido, cambios ajenos preservados, rutas protegidas identificadas y camino
de vuelta escrito **antes** de editar.

## 1. Comprobar Git antes de tocar nada

Ejecutar y leer, en este orden:

```bash
git status --short
git log --oneline -5
git branch -vv
git remote -v
```

Interpretar:

- **Trabajo en curso ajeno** (archivos modificados o sin seguimiento que no son
  propios): no sobrescribir, no limpiar, no commitear. Confirmar con el usuario
  antes de continuar.
- **Rama actual**: si es `main`/`master` o una rama compartida, crear una rama
  nueva antes de editar.
- **Remoto**: si existe, asumir que lo publicado es inmutable. Sin `push`,
  `--force`, ni `--amend` de commits ya subidos.
- **Filtros de contenido o hooks configurados**: mencionarlos; no desactivarlos
  (`--no-verify` prohibido).

## 2. Aislar el trabajo

Elegir **una** de estas dos vías y declararla:

- **Rama nueva** desde la referencia pedida: `git checkout -b <tipo>/<tema> <base>`.
- **Copia independiente** (clon en carpeta nueva) cuando el repositorio en uso
  es una instalación operativa que no debe alterarse.

Verificar que la copia o rama no comparte bases de datos, reportes ni
credenciales con la instalación operativa.

## 3. Identificar archivos y rutas protegidas

Marcar como **no tocables** salvo autorización explícita y acotada:

- Bases y datos operativos: `*.sqlite3`, `*.db`, `data/`, respaldos, `*.bak`,
  `*-wal`, `*-journal`.
- Salida generada: `reports/`, `logs/`, exportaciones.
- Credenciales y secretos: `.env*`, `*.pem`, `*.key`, `credentials*.json`,
  `secrets*.json`, almacenes del sistema (`keyring`). Nunca imprimir su
  contenido, ni siquiera parcialmente.
- Migraciones sobre datos reales.
- Rutas de otros proyectos mencionadas como inviolables en las reglas del
  workspace.
- Configuración global del usuario fuera del repositorio.

Leer el `.gitignore` y las reglas del proyecto (`AGENTS.md`) antes de decidir:
lo ignorado por Git suele ser precisamente lo protegido.

## 4. Respaldar con verificación

Antes de modificar, dejar constancia del estado previo:

```bash
git rev-parse HEAD                 # commit base
git diff > /tmp/cambio-previo.patch  # cambios sin commitear, si los hay
sha256sum <archivos a modificar>   # huella del contenido original
```

Reglas:

- El respaldo se verifica (existe, no está vacío, se puede leer) **antes** de
  editar.
- No sobrescribir respaldos anteriores: usar rutas nuevas o versionadas.
- Para archivos no versionados por Git, copiar a una ruta de respaldo explícita
  y declararla.

## 5. Modificar de forma reversible

- Cambios pequeños y acotados a la tarea; un archivo a la vez cuando sea posible.
- Preferir edición puntual sobre reescritura completa del archivo.
- No borrar código ajeno "porque parece muerto": confirmarlo con evidencia
  (referencias, `git log`, uso real) o dejarlo.
- No mezclar en el mismo commit el cambio funcional y la limpieza cosmética.
- Si una edición sale mal, revertir ese archivo desde el respaldo o desde
  `git diff` guardado, y volver a intentar; no apilar correcciones a ciegas.

## 6. Verificar y dejar escrita la reversión

- Ejecutar solo las pruebas pertinentes al cambio (ver skill `python-regression`).
- Mostrar el diff final: `git diff` y `git status --short`.
- Dejar por escrito cómo volver atrás, por ejemplo:
  `git revert <commit>` o `git checkout <commit-base> -- <archivo>`.
- Commit local solo cuando las pruebas pasan. `push`, `merge` y cualquier
  operación destructiva quedan a decisión del usuario.

## Límites

Este procedimiento no autoriza por sí mismo ninguna operación irreversible:
solo describe cómo llegar a ella con el estado previo protegido. La
autorización la da el usuario, para una decisión concreta.
