# Diseño: contexto universal y asíncrono para CYMDIST

**Fecha:** 2026-09-27

**Estado:** propuesta aprobada en conversación; pendiente de revisión del documento
**Ámbito:** numeral 1 de la SPA RECYM y propagación del contexto a los numerales 2–7

## 1. Objetivo

RECYM permitirá seleccionar directamente, desde cualquier carpeta accesible de Windows:

- una base CYMDIST `.mdb`;
- un estudio `.zxst`, `.sxst`, `.zsxst` o `.xst`;
- cualquier alimentador/red descubierto realmente dentro de la MDB elegida.

Las tres elecciones serán independientes. Ningún nombre de alimentador, familia, estudio o carpeta —por ejemplo CA101, PA217, PE104 o ELD— determinará silenciosamente otra selección. El descubrimiento de redes será asíncrono y se ejecutará en un proceso CYMDIST aislado.

## 2. Criterios de aceptación

1. Los botones `Examinar…` permiten elegir MDB y estudio en cualquier carpeta local sin copiar los archivos.
2. Dos archivos con el mismo nombre ubicados en carpetas distintas permanecen diferenciados por su ruta canónica.
3. Cambiar la MDB conserva el estudio elegido, limpia únicamente el alimentador y descubre las redes de la nueva MDB.
4. El desplegable de alimentadores contiene solamente redes verificadas en la MDB seleccionada; no incorpora alimentadores por el nombre del estudio ni por configuraciones históricas.
5. Cambiar el estudio no cambia la MDB ni el alimentador.
6. Seleccionar un alimentador no cambia la MDB ni el estudio.
7. La operación 1.1 envía explícitamente `database_mdb`, `study_path`, `feeder_id` y `network_id`; la respuesta conserva esas identidades o falla de forma explícita.
8. El descubrimiento no persiste el contexto, no guarda el estudio y no bloquea ni derriba la API principal.
9. Todos los jobs de §§2–7 reciben el contexto completo seleccionado, sin depender de valores fijos del servidor.
10. Cancelar el selector nativo o encontrar una MDB sin redes deja la selección anterior coherente y presenta un mensaje accionable.

## 3. Decisiones de arquitectura

### 3.1 Acceso directo, sin carga por navegador

Un `<input type="file">` no expone la ruta real del archivo; los navegadores entregan un valor protegido como `C:\fakepath`. Además, copiar MDB y estudios grandes rompería la custodia del archivo original y duplicaría almacenamiento. Por ello RECYM abrirá el selector nativo de Windows y conservará la ruta absoluta original.

El entorno no incluye Tkinter. Se usará `System.Windows.Forms.OpenFileDialog`, disponible en la estación, mediante un subproceso PowerShell STA. El script será fijo; los parámetros variables viajarán por variables de entorno, no por interpolación de comandos.

### 3.2 Solicitudes autosuficientes

Cada operación que use CYMDIST recibirá el contexto completo en su payload. El estado persistido se conservará para restaurar la interfaz, pero nunca será una fuente implícita que pueda sustituir campos explícitos de la solicitud.

Precedencia por campo:

1. valor explícito de la solicitud;
2. valor persistido de la sesión local;
3. ausencia con error estructurado.

No se deducirá el alimentador desde el nombre del estudio cuando la solicitud incluya `feeder_id`.

### 3.3 Descubrimiento asíncrono y aislado

Seleccionar una MDB lanzará el job `contexto_descubrir_redes`. El worker aislado abrirá o resolverá esa MDB mediante CymPy y devolverá las redes reales. La SPA recibirá progreso y resultado por el contrato existente de jobs/SSE.

Este job será de solo lectura y no ejecutará `apply_context_selection`, no cambiará `config/settings.json` y no creará configuraciones por alimentador. Un Access Violation nativo al descargar CYME quedará contenido y reportado por el padre, como en los demás workers.

## 4. Componentes

### 4.1 Selector nativo

Nuevo módulo `src/core/windows_file_picker.py`:

```python
pick_context_file(kind, initial_dir=None, timeout=600) -> dict
```

`kind` solo admitirá `database` o `study`.

Resultado al seleccionar:

```json
{
  "ok": true,
  "cancelled": false,
  "kind": "database",
  "path": "D:\\carpeta\\base.mdb",
  "name": "base.mdb",
  "extension": ".mdb",
  "size": 123456
}
```

Resultado al cancelar:

```json
{"ok": true, "cancelled": true, "kind": "database"}
```

Validaciones posteriores al diálogo:

- ruta absoluta y canónica;
- archivo existente y regular;
- `.mdb` para `database`;
- `.zxst`, `.sxst`, `.zsxst` o `.xst` para `study`;
- estudio con tamaño mínimo ya definido por `is_usable_study_file`.

### 4.2 API del selector

Nuevo router FastAPI `src/api_app/routers/context.py`:

```http
POST /api/contexto/examinar
Content-Type: application/json

{"kind":"database","initial_dir":"D:\\Bases"}
```

La ruta será accesible únicamente con la autenticación existente y desde loopback. La llamada al selector se ejecutará fuera del event loop mediante threadpool. No devolverá contenido de los archivos.

Códigos funcionales:

- `INVALID_PICKER_KIND`
- `PICKER_UNAVAILABLE`
- `PICKER_TIMEOUT`
- `FILE_NOT_FOUND`
- `INVALID_FILE_EXTENSION`
- `STUDY_FILE_INVALID`

Cancelar no será un error.

### 4.3 Job de redes

Nueva acción allow-listed e aislada:

```text
contexto_descubrir_redes
```

Payload mínimo:

```json
{"database_mdb":"D:\\Bases\\base.mdb"}
```

Resultado:

```json
{
  "ok": true,
  "database_mdb": "D:\\Bases\\base.mdb",
  "database_connection_name": "base",
  "networks": [
    {"feeder_id":"PE104","network_id":"NET_2030_184_PE104"}
  ],
  "feeders": [
    {"feeder_id":"PE104","network_id":"NET_2030_184_PE104","label":"PE104 · NET_2030_184_PE104"}
  ],
  "n": 1,
  "source": "cympy"
}
```

El backend validará la ruta y extensión antes de iniciar CymPy. La lista `feeders` se construirá exclusivamente a partir de `networks`; para este flujo se usará `include_orphan_studies=False`.

Errores:

- `DATABASE_NOT_FOUND`
- `INVALID_DATABASE_EXTENSION`
- `NETWORK_DISCOVERY_FAILED`
- `NETWORK_DISCOVERY_TIMEOUT`
- `NO_NETWORKS_FOUND`

### 4.4 Catálogo de accesos rápidos

`GET /api/contexto/archivos` será una consulta rápida y sin CymPy. Continuará listando archivos de las carpetas configuradas como accesos rápidos y añadirá siempre las rutas actualmente seleccionadas aunque estén fuera de esas carpetas.

Cambios de contrato:

- deduplicación por ruta canónica, no por nombre base;
- etiquetas con carpeta padre cuando dos archivos tengan el mismo nombre;
- no ejecutar descubrimiento CYMDIST desde esta ruta;
- no mezclar estudios huérfanos con las redes de una MDB seleccionada;
- `operational` de una red dependerá de que exista la MDB y tenga `network_id`; el estudio global independiente se validará en 1.1.

### 4.5 Cliente React

`Step1Contexto.tsx` incorporará:

- `Examinar…` junto a MDB y estudio;
- ruta completa visible debajo de cada selector;
- indicador de progreso durante `contexto_descubrir_redes`;
- actualización de alimentadores al terminar el job;
- conservación del estudio al cambiar MDB;
- limpieza del alimentador al cambiar MDB;
- conservación de MDB/alimentador al cambiar estudio;
- inserción temporal de rutas externas en las opciones visibles;
- mensajes diferenciados para cancelación, ausencia de redes, timeout y fallo CYMDIST.

El cliente de jobs ofrecerá una variante sin inyección del contexto activo:

```typescript
runDetachedJob(action, payload, onUpdate?)
```

Esto evita que el descubrimiento de una MDB nueva herede accidentalmente el feeder o estudio anterior.

### 4.6 Aplicación del contexto

`POST /api/contexto/aplicar` validará conjuntamente pero sin inferencias:

- MDB existente y extensión `.mdb`;
- estudio existente, extensión compatible y tamaño válido;
- `feeder_id` y `network_id` presentes en el catálogo descubierto para la ruta MDB solicitada;
- respuesta con las mismas cuatro identidades solicitadas.

Si la respuesta CYMDIST no puede conservarlas, devolverá `CONTEXT_IDENTITY_MISMATCH` y la SPA no cambiará su selección.

Aplicar 1.1 podrá persistir el contexto activo y reiniciar §2, como ocurre actualmente. No guardará el estudio CYMDIST.

## 5. Seguridad y concurrencia

- Selector habilitado solo en Windows, loopback y sesión autenticada.
- Argumentos del subproceso sin concatenación de shell.
- Allowlist estricta de extensiones.
- No se devuelve contenido del archivo ni se permite enumerar una ruta arbitraria enviada por el cliente.
- El selector usa un lock para evitar múltiples diálogos simultáneos.
- El descubrimiento reutiliza el lock CYMDIST y el proceso hijo existente.
- Cada resultado incluirá la ruta MDB que originó el job; la SPA descartará respuestas tardías si el usuario ya eligió otra MDB.
- Timeout del selector: 600 s. Timeout de descubrimiento: 600 s.

## 6. Persistencia y procedencia

Solo 1.1 persiste:

- `database_mdb` y su carpeta;
- `ui_study_path` exacto;
- `active_feeder`;
- `network_id` real de la MDB;
- nombre de conexión CYMDIST resuelto por ruta.

Examinar y descubrir no persisten. Las configuraciones sintetizadas para redes nuevas no se escribirán durante el descubrimiento. Si 1.1 requiere crear una configuración mínima, registrará que es sintetizada y conservará las rutas explícitas.

## 7. Pruebas

### Unitarias

- validación de tipo/extensión/ruta del selector;
- cancelación y timeout;
- deduplicación de MDB por ruta, incluyendo nombres iguales;
- estudio externo añadido al catálogo;
- payload de descubrimiento sin contexto heredado;
- redes procedentes únicamente de la MDB;
- feeder explícito independiente del nombre del estudio;
- rechazo de identidad MDB/red inconsistente;
- respuesta tardía descartada por secuencia de selección.

### Contrato/API

- selector rechazado fuera de loopback o sin autenticación;
- `/api/contexto/archivos` no invoca CymPy;
- job de descubrimiento marcado como aislado;
- 1.1 conserva las cuatro identidades explícitas.

### Integración real

1. Seleccionar una MDB situada fuera de `database_dir`.
2. Seleccionar un estudio situado en otra carpeta fuera de `projects_dir`.
3. Descubrir redes reales y elegir una.
4. Ejecutar 1.1 y comprobar respuesta, contexto persistido, CYMDIST y supervivencia de API.
5. Repetir con dos MDB homónimas en carpetas diferentes si existen fixtures seguros; en ausencia de ellas, cubrirlo con archivos temporales unitarios.

No se ejecutarán operaciones que guarden o modifiquen el estudio durante la verificación.

## 8. Compatibilidad y migración

- Los desplegables y carpetas configuradas actuales permanecen como accesos rápidos.
- Los scripts existentes que envían contexto explícito continúan funcionando.
- Las rutas legacy de Flask no serán el mecanismo primario del selector.
- El servidor seguirá siendo local; no se habilitará selección remota de archivos.
- Windows es el único sistema soportado para `Examinar…`; en otro sistema se mostrará el campo de ruta manual y `PICKER_UNAVAILABLE`.

## 9. No objetivos

- Subir o copiar MDB/estudios al repositorio.
- Escanear recursivamente todo el disco.
- Crear o editar redes durante el descubrimiento.
- Inferir que un estudio pertenece a un alimentador por su nombre.
- Corregir automáticamente archivos Excel de entradas.
- Habilitar acceso remoto al sistema de archivos.

## 10. Fundamentación

- La separación entre estado del cliente y solicitudes autosuficientes sigue las restricciones de interacción stateless descritas por Roy Fielding en su tesis doctoral sobre arquitecturas de software en red.
- El selector nativo usa la interfaz estándar `System.Windows.Forms.OpenFileDialog` documentada por Microsoft.
- La estrategia de pruebas por contrato, regresión e integración sigue las categorías destacadas por la revisión sistemática de pruebas de aplicaciones web publicada en *Journal of Systems and Software*.

Referencias:

- Fielding, R. T. *Architectural Styles and the Design of Network-based Software Architectures*, doctoral dissertation, University of California, Irvine, 2000. https://ics.uci.edu/~fielding/pubs/dissertation/rest_arch_style.htm
- Microsoft. *OpenFileDialog Class (System.Windows.Forms)*. https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.openfiledialog?view=netframework-4.8.1
- MDN Web Docs. *`<input type="file">`*. https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/file
- Doğan, S., Betin-Can, A., Garousi, V. *Web application testing: A systematic literature review*. Journal of Systems and Software 91 (2014). https://www.sciencedirect.com/science/article/pii/S0164121214000223
