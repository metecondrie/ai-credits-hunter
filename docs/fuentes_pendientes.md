# Inventario canónico de fuentes — AI Credits Hunter

**Este archivo es el inventario permanente del proyecto.** Ninguna fuente se elimina
por no haber podido implementarse: se actualiza su estado y se conserva el motivo.

- **Última actualización:** 2026-11-10 (P1.3, rama `feature/p13-recover-sources`).
- **Fuentes en el catálogo del motor:** **22 registradas y 22 habilitadas**.
  P1.3 corrigió el parser de `robots.txt`, reactivó Alibaba Model Studio y AWS
  Educate, e incorporó GitHub Student Developer Pack (ofertas propias de GitHub),
  AWS Activate y Google Skills credits.
- **Fuentes en este inventario:** 23 evaluadas (P1.2, actualizadas en P1.3). Las 11
  operativas previas a P1.2 y la descartada de P1.1 se listan al final como contexto.
- Todas las consultas fueron HTTP GET de lectura a las URLs oficiales, sin claves,
  sin llamadas a modelos y sin consumo de créditos. Fecha de comprobación:
  **2026-11-10** (UTC).

## Estados

| Estado | Significado |
|---|---|
| `PENDIENTE` | Todavía no evaluada en profundidad, o evaluada sin poder determinar un beneficio fiable. |
| `VALIDADA` | Beneficio oficial comprobado con evidencia literal, aún sin extractor incorporado. |
| `INTEGRADA` | Extractor incorporado, con fixture y pruebas; funciona en el motor. |
| `BLOQUEADA` | Existe beneficio (o la fuente es relevante) pero no hay método de extracción fiable. |
| `DESCARTADA` | Sin beneficio aplicable o verificable en la página consultada. |

## Resumen

| Estado | Cantidad |
|---|---|
| INTEGRADA | 11 |
| VALIDADA | 0 |
| BLOQUEADA | 4 |
| DESCARTADA | 7 |
| PENDIENTE | 1 |
| **Total** | **23** |

---

## Prioridad alta

### 1. Alibaba Cloud Model Studio — `INTEGRADA` (recuperada en P1.3)
- **URL:** https://www.alibabacloud.com/help/en/model-studio/new-free-quota
- **Categoría:** API de inferencia / cuota gratuita · **Prioridad:** alta
- **HTTP:** 200, 43 463 bytes, 24 304 caracteres de texto.
- **Beneficio detectado:** cuota gratuita para nuevos usuarios, **válida 90 días**
  desde la activación del servicio, la publicación del modelo o la aprobación de la
  solicitud (lo que ocurra más tarde).
- **Evidencia literal:** «The free quota is valid for 90 days, starting from the date
  you activate Alibaba Cloud Model Studio…»; «After the free quota is exhausted, you
  are automatically billed on a pay-as-you-go basis. To avoid unexpected charges,
  enable Free Quota Only in advance so that the service stops when the quota runs out.»
- **Condiciones:** desde el 15 de septiembre hay que completar la información de la
  cuenta antes de activar. **`Free Quota Only` viene desactivado por defecto.**
- **Tarjeta / país:** no publicados → No confirmado.
- **Clasificación:** `PRUEBA_GRATUITA`, sin porcentaje.
- **Motivo de aceptación:** beneficio y plazo publicados, más la advertencia de cargo
  y su protección, todo en HTML servido.
- **Riesgo documentado:** al agotarse la cuota **se factura automáticamente**. El
  extractor exige que la advertencia y la protección estén presentes; si la página
  deja de publicarlas, devuelve cero candidatos en vez de publicar el beneficio a
  ciegas. Los importes por modelo viven en la consola, no en la página: no se inventan.
- **Extractor:** `alibaba_free_quota` · **Fixture:** `alibaba-model-studio-free-quota.html`
- **Bloqueo resuelto en P1.3:** el parser mínimo de robots reducía cada regla con
  comodín a su prefijo previo al `*`, así que `Disallow: /*.json` producía el prefijo
  `/` y bloqueaba todo el host. Se corrigió el emparejamiento (`_robots_match` en
  `ach/fetch.py`): el comodín vale cualquier secuencia, el resto es literal y se
  respeta el ancla `$` y la query string. **No se desactivó ni se eludió la
  protección**: verificado contra las 20 reglas reales del sitio, las rutas
  prohibidas (`/api/…`, `/*.json`, `/*?page=…`, `/admin`) siguen bloqueadas.
- **Verificación en vivo (2026-11-10, corrida funcional con base temporal):**
  HTTP 200, `robots_bloqueado=False`, 1 candidato `PRUEBA_GRATUITA`. Fuente
  reactivada (`enabled=True`).

### 2. Cerebras Inference — `INTEGRADA`
- **URL:** https://inference-docs.cerebras.ai/support/pricing
- **Categoría:** API de inferencia / crédito promocional · **Prioridad:** alta
- **HTTP:** 200, 243 447 bytes, 2 347 caracteres de texto.
- **Beneficio detectado:** crédito promocional **único de USD 5**, que **vence a los
  30 días** de activado.
- **Evidencia literal:** «Add a valid payment method to receive a one-time $5
  promotional credit. The credit expires 30 days after activation. You will not be
  charged or automatically enrolled in paid usage.»; «For development, evaluation,
  and experimentation; not intended for production use.»
- **Condiciones:** requiere **método de pago válido**; crédito no transferible, sin
  valor en efectivo, revocable por fraude/abuso/cuentas duplicadas. Al vencer o
  agotarse, el acceso a API y Playground se pausa salvo compra de créditos PayGo.
- **Tarjeta:** **sí** (publicado) · **País:** No confirmado.
- **Clasificación:** `CREDITO`, sin porcentaje.
- **Motivo de aceptación:** aunque la tabla de tiers se renderiza por JavaScript, las
  notas con el beneficio concreto **sí están en el HTML servido** y son verificables.
- **Limitación:** no se extraen los límites por modelo de la tabla (cliente). El nivel
  gratuito se publica como no apto para producción.
- **Extractor:** `cerebras_promo_credit` · **Fixture:** `cerebras-promo-credit.html`

### 3. Modal — `INTEGRADA`
- **URL:** https://modal.com/pricing
- **Categoría:** infraestructura / crédito de cómputo recurrente · **Prioridad:** alta
- **HTTP:** 200, 342 733 bytes, 13 466 caracteres de texto.
- **Beneficio detectado:** plan **Starter a USD 0 + cómputo/mes** con **USD 30 mensuales
  de créditos de cómputo**, 3 asientos, 100 contenedores + 10 GPU de concurrencia y
  1 TiB/mes de egreso gratuito.
- **Evidencia literal:** «Starter … $0 + compute / month $30 / month free credits
  3 workspace seats included 100 containers + 10 GPU concurrency … 1 TiB / month
  free network egress».
- **Condiciones:** el cómputo por encima del crédito incluido se factura por uso.
- **Tarjeta / país / vencimiento:** no publicados → No confirmado.
- **Clasificación:** `CREDITO`, sin porcentaje.
- **Motivo de aceptación:** cifra y plan publicados en HTML servido.
- **Distinción exigida:** el crédito de cómputo **no** es un descuento del 100 % sobre
  un plan pago, y los endpoints son facturables. Queda explícito en `notes`.
- **Extractor:** `modal_free_credits` · **Fixture:** `modal-free-credits.html`

### 4. GitHub Student Developer Pack — `INTEGRADA` (P1.3, solo ofertas de GitHub)
- **URL:** https://education.github.com/pack
- **Categoría:** beneficio estudiantil / pack de terceros · **Prioridad:** alta
- **HTTP:** 200, 271 368 bytes, 32 327 caracteres de texto.
- **Beneficio detectado:** pack para estudiantes con ofertas de partners; ejemplos
  literales: «1 year domain name registration on the .me TLD», «1 SSL certificate
  free for 1 year».
- **Condiciones:** elegibilidad estudiantil verificada por GitHub Education.
- **Tarjeta / país:** depende de cada partner → No confirmado.
- **Integración en P1.3:** se resolvió el problema de agregación extrayendo
  **únicamente las ofertas propias de GitHub**, que tienen ancla literal estable,
  y dejando fuera las de terceros:
  - «**Free GitHub Pro while you are a student.**»
  - «**GitHub Copilot Student is available to verified students.** The plan includes
    unlimited code completions and an allowance of GitHub AI Credits, plus limited
    chat and agent usage with models available through auto model selection only.»
- **Condiciones:** estudiantes verificados por GitHub Education. Copilot Student
  **no** es acceso ilimitado a todos los modelos: chat y agentes quedan limitados a
  selección automática de modelo. Tarjeta y país: No confirmado.
- **Clasificación:** `BENEFICIO_ESTUDIANTIL`, `student_required=yes`, sin porcentaje.
- **Verificación en vivo (2026-11-10):** HTTP 200, **2 candidatos**.
- **Extractor:** `github_student_pack` (id `github-student-pack`).
- **Sigue fuera:** las ofertas de terceros del pack (Namecheap, .TECH, Codédex, etc.).
  No se extrajeron por ser un catálogo ajeno y cambiante; quedan como trabajo
  pendiente si se quiere ampliar, validando cada una en su propia página oficial.

### 5. Azure for Students — `INTEGRADA`
- **URL:** https://azure.microsoft.com/en-us/pricing/offers/ms-azr-0170p
- **Categoría:** cloud / crédito estudiantil · **Prioridad:** alta
- **HTTP:** 200, 154 447 bytes, 17 099 caracteres de texto.
- **Beneficio detectado:** **USD 100** en créditos Azure para usar en los primeros
  **12 meses**, más servicios gratuitos seleccionados.
- **Evidencia literal:** «Azure for Students gets you started with $100 in Azure
  credits to be used within the first 12 months, plus select free services …
  **without requiring a credit card at sign-up**.»
- **Condiciones:** «You must affirm that you are age 18 or older and attend an
  accredited, degree-granting two-year or four-year educational institution where
  you're a full-time student.» Los créditos no usados no se acumulan ni se transfieren.
- **Tarjeta:** **no** (publicado) · **Estudiante:** **sí** · **País:** No confirmado.
- **Clasificación:** `BENEFICIO_ESTUDIANTIL`, sin porcentaje.
- **Motivo de aceptación:** importe, plazo, elegibilidad y ausencia de tarjeta
  publicados literalmente.
- **Extractor:** `azure_student_credit` · **Fixture:** `azure-for-students.html`

### 6. Google Cloud Free Trial — `INTEGRADA`
- **URL:** https://cloud.google.com/signup-faqs
- **Categoría:** cloud / crédito de bienvenida · **Prioridad:** alta
- **HTTP:** 200, 1 611 815 bytes, 45 575 caracteres de texto.
- **Beneficio detectado:** **USD 300** de crédito de bienvenida válido **90 días**,
  más productos Free Tier hasta sus límites mensuales.
- **Evidencia literal:** «…preloaded with $300 in free Welcome credit which is valid
  for 90 days.»; «…auto-closes if you spend the $300 credit or 90 days pass from
  signup, and you won't be charged unless you manually upgrade to a paid account.»
- **Condiciones:** cuentas nuevas elegibles. «You can use your personal credit card
  to verify your identity, without being personally responsible for any payment…»
- **Tarjeta:** **sí**, para verificar identidad (no hace falta corporativa) ·
  **País:** No confirmado.
- **Clasificación:** `CREDITO`, sin porcentaje.
- **Motivo de aceptación:** importe, validez y política de cargos publicados.
- **Extractor:** `gcp_free_trial` · **Fixture:** `gcp-free-trial.html`

### 7. AWS Educate — `INTEGRADA` (recuperada en P1.3)
- **URL:** https://aws.amazon.com/education/awseducate/
- **Categoría:** educación / laboratorios gratuitos · **Prioridad:** alta
- **HTTP:** 200, 380 405 bytes, 8 750 caracteres de texto.
- **Beneficio detectado:** laboratorios prácticos gratuitos y recursos de aprendizaje.
- **Evidencia literal:** «**No credit card needed**»; «Learners as young as 13 can
  register for AWS Educate with just an email address, gaining access to free
  hands-on labs to learn and practice cloud skills in real-time.»
- **Tarjeta:** **no** (publicado) · **Estudiante:** sí (desde 13 años) ·
  **País:** No confirmado.
- **Clasificación:** `BENEFICIO_ESTUDIANTIL`, sin porcentaje.
- **Motivo de aceptación:** beneficio y ausencia de tarjeta publicados.
- **Límite respetado:** **no se inventan créditos para APIs de IA**; la página no los
  publica. Queda explícito en `notes`.
- **Extractor:** `aws_educate` · **Fixture:** `aws-educate.html`
- **Bloqueo resuelto en P1.3:** mismo defecto y mismo arreglo que Alibaba. De las
  266 reglas `Disallow` del grupo `*` en `aws.amazon.com/robots.txt`, ninguna
  prohíbe `/education/awseducate/`; el bloqueo lo causaba el prefijo `/` derivado
  de comodines como `/*/blogs/*/tag/`. Tras corregir el emparejamiento se verificó
  que `/blogs/…/tag/…`, `/activate/event/…` y
  `/government-education/nonprofits/aws-serve/` **siguen bloqueadas**.
- **Verificación en vivo (2026-11-10):** HTTP 200, `robots_bloqueado=False`,
  1 candidato `BENEFICIO_ESTUDIANTIL` con `card_required=no`. Fuente reactivada.

### 8. AWS Activate — `INTEGRADA` (P1.3, solo startups)
- **URL:** https://aws.amazon.com/activate/
- **Categoría:** cloud / créditos para startups · **Prioridad:** alta
- **HTTP:** 200, 398 114 bytes, 10 128 caracteres de texto.
- **Beneficio detectado:** «Get **up to $200,000** in AWS Activate Credits and expert
  support». Créditos canjeables en modelos de terceros vía Amazon Bedrock.
- **Condiciones:** para **startups elegibles**, no necesariamente usuarios
  individuales; el importe es «hasta», no garantizado.
- **Tarjeta / país:** No confirmado.
- **Integración en P1.3:** se incorporó con la elegibilidad explícita, que era el
  motivo por el que no se integraba. Ancla literal: «Apply to receive **up to
  $200,000** in AWS Activate Credits to offset costs on infrastructure, data
  services, and AI/ML models. Credits are redeemable on third-party models on
  Amazon Bedrock.»
- **Cómo se evita el engaño:** el título dice «**hasta** USD 200,000 … para startups
  elegibles»; `eligibility` aclara que son **startups que aplican y son admitidas, no
  usuarios individuales**, y que el importe es un tope, no una asignación garantizada.
  `confidence=media` por esa condicionalidad. Se distingue de AWS Educate
  (estudiantes) y de las ofertas para usuarios individuales.
- **Clasificación:** `CREDITO`, sin porcentaje.
- **Verificación en vivo (2026-11-10):** HTTP 200, 1 candidato.
- **Extractor:** `aws_activate_credits` (id `aws-activate-startups`).

### 9. Google Gemini API — `BLOQUEADA`
- **URL:** https://ai.google.dev/gemini-api/docs/pricing/
- **Categoría:** API de inferencia / free tier · **Prioridad:** alta
- **HTTP:** 200, 172 963 bytes, **60 caracteres de texto** (solo el título).
- **Beneficio esperado:** Free Tier real por modelo (referencia de la tarea).
- **Motivo del bloqueo:** contenido **100 % renderizado por JavaScript**. En P1.1 ya
  se había descartado por lo mismo. En P1.2 se probó una alternativa oficial:
  `https://ai.google.dev/gemini-api/docs/pricing.md` → HTTP 200, 172 963 bytes,
  **los mismos 60 caracteres de texto**. No hay versión markdown ni JSON con precios.
- **Estado:** se conserva como `BLOQUEADA`, **no** como descartada: el beneficio
  existe, falta un método de extracción gratuito y reproducible (navegador o una
  versión oficial estática que hoy no responde).
- **Pendiente:** revisar si Google publica un endpoint estático o un `llms.txt` con
  los precios; no simular el free tier mientras tanto.

---

## Prioridad secundaria

### 10. Azure Free — `INTEGRADA`
- **URL:** https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account
- **Categoría:** cloud / crédito + servicios gratuitos · **Prioridad:** secundaria
- **HTTP:** 200, 502 054 bytes, 28 244 caracteres de texto.
- **Beneficio detectado:** **USD 200** de crédito para explorar Azure hasta **30 días**,
  más cantidades mensuales de 20+ servicios por 12 meses y **65+ servicios siempre
  gratuitos**.
- **Evidencia literal:** «Get free services and a $200 credit to explore Azure for up
  to 30 days.»; «Free monthly amounts of 65+ always-free services»; «Spending
  protection—credit card won't be charged».
- **Condiciones:** clientes nuevos; «During the signup verification process, there may
  be a temporary $1 authorization placed on your card, which will be reversed upon
  verification.» Hay que pasar a pay-as-you-go para continuar tras el plazo.
- **Tarjeta:** **sí** (verificación, con autorización temporal de USD 1 revertida) ·
  **País:** No confirmado.
- **Clasificación:** `CREDITO`, sin porcentaje.
- **Motivo de aceptación:** importe, plazo y protección de gasto publicados.
- **Nota de HTML:** la página tiene atributos anidados que `to_text` no limpia del
  todo; se eligió el ancla de una oración completa y limpia, no fragmentos de atributos.
- **No duplicada:** es una oferta **distinta** de Azure for Students (importe, plazo,
  elegibilidad y URL diferentes); `dedupe_extra` y producto son distintos.
- **Extractor:** `azure_free_account` · **Fixture:** `azure-free-account.html`

### 11. Replicate — `DESCARTADA`
- **URL:** https://replicate.com/pricing
- **HTTP:** 200, 87 140 bytes, 8 349 caracteres de texto.
- **Observado:** «You only pay for what you use on Replicate». No hay free tier ni
  créditos. Un banner anuncia «Minimax H3 Lite and Highspeed are 50% until end of year».
- **Motivo del descarte:** el único descuento es un **banner transitorio sin precio
  base comparable publicado** en la página; según la regla de P0.3 sería
  `SIN_BASE_VERIFICADA`, no un descuento publicable. No hay beneficio gratuito.
- **Pendiente:** si se quiere seguir ese banner, hay que obtener el precio base
  oficial de esos modelos y verificar la vigencia; no se implementó para no inventar.

### 12. Mistral AI — `DESCARTADA`
- **URL:** https://docs.mistral.ai/
- **HTTP:** 200, 766 146 bytes, 6 596 caracteres de texto.
- **Observado:** portada de documentación con guías («Extract a validated Python
  object from free text…»). La única coincidencia de «free» es «free text», ajena a
  un beneficio.
- **Motivo del descarte:** la página consultada **no documenta ningún beneficio
  gratuito**. No se presupone promoción.
- **Pendiente:** si existe un free tier, estaría en otra página oficial (por ejemplo
  la de precios de la plataforma); no se consultó para no ampliar el alcance.

### 13. SambaNova Cloud — `BLOQUEADA`
- **URL:** https://docs.sambanova.ai/
- **HTTP:** **403 Forbidden**.
- **Motivo del bloqueo:** el servidor rechaza la lectura. No se intentó sortear el
  bloqueo (sin VPN, proxies ni evasión).
- **Pendiente:** revisar condiciones de acceso o una URL oficial alternativa.

### 14. NVIDIA API Catalog — `BLOQUEADA`
- **URL:** https://build.nvidia.com/
- **HTTP:** 200, 136 489 bytes, **1 381 caracteres de texto**.
- **Motivo del bloqueo:** cáscara renderizada por JavaScript; sin evidencia literal
  de créditos ni cuotas en el HTML servido.
- **Pendiente:** buscar una página de documentación estática oficial.

### 15. Together AI — `PENDIENTE`
- **URL:** https://www.together.ai/pricing
- **HTTP:** 200, 628 973 bytes, 13 400 caracteres de texto.
- **Observado:** tabla de precios por millón de tokens servida en HTML. Aparece el
  token «Free» en una fila («Tev1 4B Experimental $0.04 Free»), pero **la semántica
  de las columnas no es inequívoca** en el texto aplanado: no se puede afirmar si
  «Free» es el precio de entrada, de salida o una condición.
- **Motivo del estado:** evaluada superficialmente; **no se implementó para no
  atribuir un beneficio mal interpretado**. No es un descarte: puede haber un modelo
  gratuito real.
- **Pendiente:** analizar la estructura de la tabla (columnas input/output/cached) y,
  si se confirma un modelo con precio 0, integrarlo como `MODELO_GRATUITO`.

### 16. Fireworks AI — `INTEGRADA`
- **URL:** https://fireworks.ai/pricing
- **Categoría:** API / acceso gratuito por tiempo limitado · **Prioridad:** secundaria
- **HTTP:** 200, 609 578 bytes, 11 165 caracteres de texto.
- **Beneficio detectado:** «**Muse Glimmer 30B SFT is free through November 30** In the
  UI and the Serverless Training API. **No credit card required**.»
- **Condiciones:** acotado a la UI y la Serverless Training API; el resto del uso se
  factura con créditos prepagos.
- **Tarjeta:** **no** (publicado) · **País:** No confirmado.
- **Clasificación:** `PRUEBA_GRATUITA` (acceso gratuito temporal), sin porcentaje.
- **Motivo de aceptación:** modelo, alcance, fecha tope y ausencia de tarjeta
  publicados literalmente.
- **Honestidad sobre el vencimiento:** la página dice «November 30» **sin año**. No se
  inventa el año ni se fija `expires_at`; la fecha literal queda en título y `notes`.
- **Extractor:** `fireworks_free_model` · **Fixture:** `fireworks-free-model.html`

### 17. fal.ai — `DESCARTADA`
- **URL:** https://fal.ai/pricing
- **HTTP:** 200, 215 023 bytes, 7 802 caracteres de texto.
- **Observado:** precios por unidad y «Units per $1»; las coincidencias de «free» son
  etiquetas de producto («Free Tools», «Background Remover», «Image Upscaler»).
- **Motivo del descarte:** no hay crédito, cuota gratuita ni condiciones publicadas;
  «Free Tools» es marketing de herramientas, no un beneficio con magnitud verificable.

### 18. RunPod — `DESCARTADA`
- **URL:** https://www.runpod.io/pricing
- **HTTP:** 200, 329 754 bytes, 12 776 caracteres de texto.
- **Observado:** precios de GPU por hora; **cero** coincidencias de «free», «credit»
  o «trial».
- **Motivo del descarte:** sin beneficio gratuito documentado en la página consultada.

### 19. Z.ai — `DESCARTADA`
- **URL:** https://docs.z.ai/
- **HTTP:** 200, 302 946 bytes, 7 352 caracteres de texto.
- **Observado:** portada de documentación; cero coincidencias de «free» o «credit».
- **Motivo del descarte:** la página consultada no documenta beneficio gratuito.

### 20. Hugging Face Spaces — `DESCARTADA`
- **URL:** https://huggingface.co/spaces
- **HTTP:** 200, 385 826 bytes, 5 210 caracteres de texto.
- **Observado:** galería de Spaces de la comunidad. La coincidencia de «free»
  («free, no GPU queue») pertenece a la **descripción de un Space publicado por un
  usuario**, no a una oferta oficial de Hugging Face.
- **Motivo del descarte:** contenido generado por usuarios, sin beneficio oficial
  verificable. **No confundir** con Hugging Face Inference Providers (descartada en
  P1.1 por declarar «Free Users: None»).
- **Pendiente:** el free tier de hardware de Spaces, si existe, se documentaría en
  otra página oficial; no se consultó.

### 21. OpenAI API — `BLOQUEADA`
- **URL:** https://openai.com/api/pricing/
- **HTTP:** **403 Forbidden**.
- **Motivo del bloqueo:** el servidor rechaza la lectura. No se intentó sortearlo.
- **Nota:** el blog de OpenAI ya se sigue vía RSS (`openai-news-rss`), que es una
  fuente distinta y sigue operativa.

### 22. Anthropic — `DESCARTADA`
- **URL:** https://docs.anthropic.com/
- **HTTP:** 200, 519 203 bytes, 3 613 caracteres de texto.
- **Observado:** portada de documentación; cero coincidencias de «free» o «credit».
- **Motivo del descarte:** sin beneficio gratuito documentado en la página consultada.

### 23. Google Cloud para estudiantes — `INTEGRADA` (P1.3, solo Google Skills credits)
- **URL:** https://cloud.google.com/edu/students
- **Categoría:** educación / créditos · **Prioridad:** secundaria
- **HTTP:** 200, 1 620 401 bytes, 39 805 caracteres de texto.
- **Beneficio detectado:** «**200 free Google Skills credits**. Credits expire one
  year after they are issued», más el «Google Cloud Free Program: $300 in free
  credits and 20+ free products».
- **Integración en P1.3:** se integró **solo el beneficio distinto**, los
  «**200 free Google Skills credits**» con «Credits expire one year after they are
  issued». Los USD 300 del Free Program **no** se extrajeron aquí porque son la misma
  oferta que `gcp-free-trial`: así no se duplica.
- **Condiciones:** publicado en la página de Google Cloud para estudiantes; la página
  no detalla un requisito de verificación académica para estos créditos, por lo que
  `student_required=unknown` y no se afirma elegibilidad exclusiva. Vencimiento:
  un año desde la emisión. Tarjeta y país: No confirmado.
- **Clasificación:** `BENEFICIO_ESTUDIANTIL`, sin porcentaje.
- **Verificación en vivo (2026-11-10):** HTTP 200, 1 candidato, clave de dedupe
  distinta de la del Free Trial.
- **Extractor:** `gcp_student_skills` (id `gcp-students-skills-credits`).

---

## Contexto: fuentes ya procesadas (NO re-evaluadas en P1.2)

**Operativas antes de P1.2 (11):** `openrouter-free-models`, `deepseek-pricing`,
`cloudflare-workers-ai-pricing`, `kiro-pricing`, `vercel-ai-gateway-pricing`,
`groq-free-plan`, `stability-welcome-credits`, `cohere-trial-key`, `openai-news-rss`,
`google-ai-blog-rss`, `huggingface-blog-rss`.

**Descartada en P1.1:** Hugging Face Inference Providers
(`huggingface.co/docs/inference-providers/pricing`) — la página declara «Free Users:
None» y que las cuentas gratuitas deben comprar créditos o pasar a PRO. **No es la
misma fuente** que Hugging Face Spaces (ítem 20).

## Trabajo pendiente conservado

| Fuente | Estado | Qué falta |
|---|---|---|
| ~~Alibaba Cloud Model Studio~~ | INTEGRADA en P1.3 | Nada: robots corregido y reactivada. |
| ~~AWS Educate~~ | INTEGRADA en P1.3 | Nada: robots corregido y reactivada. |
| ~~GitHub Student Developer Pack~~ | INTEGRADA en P1.3 | Solo ofertas propias de GitHub. Las de terceros del pack siguen fuera: validar cada una en su página oficial si se quiere ampliar. |
| ~~AWS Activate~~ | INTEGRADA en P1.3 | Nada: publicado con elegibilidad explícita de startup y como tope, no garantizado. |
| ~~Google Cloud estudiantes~~ | INTEGRADA en P1.3 | Nada: solo los 200 Google Skills credits, sin duplicar el Free Trial. |
| Gemini API | BLOQUEADA | Método de extracción estático oficial (la variante `.md` no sirve). |
| SambaNova Cloud | BLOQUEADA | Acceso: HTTP 403. |
| NVIDIA API Catalog | BLOQUEADA | Contenido JS; buscar documentación estática. |
| OpenAI API | BLOQUEADA | Acceso: HTTP 403. |
| Together AI | PENDIENTE | Desambiguar columnas de la tabla antes de afirmar un modelo gratuito. |
| Replicate, Mistral, fal.ai, RunPod, Z.ai, HF Spaces, Anthropic | DESCARTADA | Sin beneficio en la página consultada; revisar otra página oficial solo si aparece evidencia. |
