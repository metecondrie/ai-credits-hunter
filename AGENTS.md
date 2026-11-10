# AGENTS.md — Reglas permanentes de trabajo (AI Credits Hunter)

Reglas estables para cualquier persona o agente que abra este repositorio.
Complementan, no reemplazan, la hoja de ruta de la sección 12 del `README.md`.

## 1. Roles

- **Un desarrollador principal** por ejecución: reproduce, modifica, prueba y
  documenta el cambio.
- **Un revisor opcional** (`code-reviewer`), de solo lectura, que se invoca
  únicamente cuando el usuario pide una revisión final explícita.
- Sin Agent Teams, sin cadenas de subagentes ni orquestación multiagente para
  una tarea que resuelve una sola persona.

## 2. Alcance por ejecución

- **Una tarea concreta por ejecución**: un único pendiente (un P0 o una mejora
  P1) de la sección 12 del `README.md`. Se reproduce, se corrige, se prueba y
  se entrega.
- Concluir al verificar el resultado observable. No abrir auditorías generales,
  refactorizaciones ni arreglos "de paso" sobre código no relacionado.
- Si aparece un problema nuevo, se anota como pendiente en el `README.md`; no se
  resuelve en la misma ejecución.

## 3. Zonas prohibidas

- **Producción y bases operativas**: no modificar ni abrir en escritura `data/`,
  `reports/`, `*.sqlite3`, `*.db`, respaldos ni bases históricas. Las pruebas
  usan bases temporales.
- **Credenciales**: no leer, escribir, imprimir ni mover claves, tokens, cookies
  ni archivos `.env`. Las claves de IA viven en el Credential Manager del
  sistema (`keyring`), nunca en el repositorio, fixtures, logs o reportes.
- **Migraciones**: no ejecutarlas sobre datos reales ni reabrir las históricas.
- **WorkBuddy**: jamás leer ni modificar `~/.workbuddy*`, `~/WorkBuddy*` ni
  `workbuddy.db`.

## 4. Aislamiento

- Trabajar siempre sobre una **rama nueva** o una **copia/clon independiente**.
- `main` es referencia: no se modifica directamente.
- Preservar el estado previo: `git status` antes de tocar nada. Si hay cambios
  ajenos en curso, no sobrescribirlos ni limpiarlos.

## 5. Costo

- Presupuesto incremental **USD 0**. No usar servicios pagos, APIs con costo ni
  créditos de terceros sin autorización explícita para esa ejecución concreta.
- Pruebas sin red: mocks y fixtures. No consumir cuota para "ver si funciona".

## 6. Operaciones irreversibles

- **Nunca en automático**: `git push`, `merge`, `rebase`, `reset --hard`,
  `checkout --` / `restore`, `clean -f`, borrado de ramas, `--amend` de commits
  publicados ni `--no-verify`.
- Se proponen y se ejecutan solo con autorización explícita y acotada a esa
  decisión. Una autorización no se extiende por implicancia a la siguiente.
- El commit local procede cuando las pruebas pertinentes pasan; publicar es
  otra decisión.

## 7. Verificación y cierre

- Evidencia sobre opinión: comando ejecutado, salida real, archivo y línea.
- Separar siempre lo **verificado** de lo **inferido** y de lo **no verificado**.
- Cierre: qué se cambió, qué se probó y con qué resultado, qué quedó pendiente.
  No declarar "terminado" solo por el número de tests.

## 8. Comandos útiles

| Acción | Comando |
|---|---|
| Inicializar base local | `python -m ach init` |
| Pruebas de IA (offline) | `python -m unittest discover -s tests -p "test_ach_ai.py"` |
| Pruebas unitarias | `python -m unittest discover -s tests -p "test_ach_unit.py"` |
| Pruebas de extractores | `python -m unittest discover -s tests -p "test_ach_extractors.py"` |
| Integración sin red | `ACH_OFFLINE=1 python -m unittest discover -s tests -p "test_ach_integration.py"` |

Solo biblioteca estándar de Python >= 3.11: no agregar dependencias ni hacer
`pip install` para resolver una tarea.

## 9. Extensiones de este repositorio

| Componente | Ruta | Cuándo se usa |
|---|---|---|
| Skill `safe-change` | `.qoder/skills/safe-change/SKILL.md` | Antes de modificar archivos de un repositorio existente |
| Skill `python-regression` | `.qoder/skills/python-regression/SKILL.md` | Para reproducir un defecto y dejarlo cubierto por pruebas |
| Skill `evidence-validator` | `.qoder/skills/evidence-validator/SKILL.md` | Para validar una oferta, promoción o descuento de IA |
| Agente `code-reviewer` | `.qoder/agents/code-reviewer.md` | Revisión final de solo lectura, solo a pedido explícito |
