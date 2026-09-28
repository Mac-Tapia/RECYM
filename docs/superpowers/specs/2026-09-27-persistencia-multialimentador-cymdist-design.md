# Diseño: persistencia física multi-alimentador y diagnóstico coloreado CYMDIST

**Fecha:** 2026-09-27

**Estado:** diseño aprobado en conversación; pendiente de revisión del documento

**Extiende:** `docs/superpowers/specs/2026-09-27-contexto-universal-cymdist-design.md`

**Ámbito:** guardado físico de acciones mutantes en §§1–3, diagnóstico real coloreado, nuevo paso 3.4 y renumeración del flujo proyectado.

## 1. Objetivo

RECYM garantizará que cada acción que modifica un modelo CYMDIST quede físicamente persistida y verificada para el alimentador solicitado, incluso cuando varias redes compartan la misma MDB y el mismo estudio.

El diagnóstico ejecutará LoadFlow real y obtendrá vistas nativas CYMDIST coloreadas por nivel de tensión (`VoltageLevel`) y cargabilidad (`LoadingLevel`). Después de 3.3 se incorporará 3.4 como estado situacional autoritativo para el informe. El flujo con cargas nuevas pasará a ser 5.1.

## 2. Criterios de aceptación

1. Una operación mutante no informa éxito si el cambio solo quedó en memoria.
2. 1.2 confirma escritura de cabecera, guardado del estudio, actualización de BD y guardado del proyecto.
3. 2.3, Guardar inclusiones, 3.2 y 3.3 guardan físicamente las modificaciones que les corresponden.
4. 2.1 y las demás consultas no persisten cambios; cualquier ajuste temporal se restaura.
5. Cada escritura queda limitada al `network_id` explícito y falla si la red no pertenece a la MDB/estudio solicitados.
6. Al actualizar dos alimentadores del mismo estudio, el segundo abre la versión guardada por el primero y ambos cambios permanecen después de reabrir.
7. Antes de cada escritura se genera un respaldo recuperable del estudio.
8. Después de guardar, un proceso nuevo reabre el estudio, relee los campos modificados y confirma las cuatro identidades del contexto.
9. 2.1 produce evaluaciones numéricas y capturas reales `VoltageLevel` y `LoadingLevel`; no se aceptan imágenes sintéticas.
10. 3.4 ejecuta LoadFlow situacional real inmediatamente después de 3.3 y genera las dos capturas situacionales verificadas para el informe.
11. El antiguo 5.2 pasa a 5.1 como flujo proyectado; el flujo general se retira del recorrido principal.
12. El informe solo reutiliza LoadFlow y capturas cuya huella MDB–estudio–alimentador–red coincida con el contexto activo.

## 3. Clasificación de operaciones

### 3.1 Operaciones mutantes con commit obligatorio

| Paso | Operación | Cambios físicos | Commit requerido |
|---|---|---|---|
| 1.2 | Cargar cabecera | demanda P/Q, tensiones de fuente | estudio + `db.Update` + `SaveProject` |
| 2.3 | Aplicar correcciones | equipos, tensiones base y correcciones aprobadas | estudio; BD/proyecto si cambia biblioteca/equipo |
| 2 | Guardar inclusiones | conexión, símbolo, capacidad y FP de SpotLoad | estudio |
| 3.1 | Liberar clientes anteriores | estado de conexión/bloqueo cuando exista cambio real | estudio |
| 3.2 | Cargar EA/Pot | KWH, kW/kvar, Locked, conexión | estudio |
| 3.3 | Load Allocation | demanda, locks y reparto CYMDIST | estudio; confirmar guardado COM cuando sea su motor |
| 4.x | Crear/conectar cargas nuevas | dispositivos y estado de conexión | estudio |

El alcance inmediato solicitado cubre §§1–3. §4 conservará el mismo contrato de commit porque es mutante, pero su rediseño funcional no forma parte de esta ampliación.

### 3.2 Operaciones de solo lectura

- 1.1: verificar/conectar y activar contexto; no guarda el estudio.
- 2.1: diagnóstico, LoadFlow diagnóstico y capturas coloreadas.
- 2.2: proponer correcciones.
- Estados, inventarios, vistas preliminares y consultas.

Si una operación de lectura necesita cambiar parámetros de simulación o el modo visual, tomará un snapshot y los restaurará antes de cerrar. No ejecutará `study.Save`, `db.Update` ni `SaveProject`.

## 4. Unidad de trabajo persistente

### 4.1 Identidad y exclusión mutua

La unidad de serialización será la ruta canónica del estudio, no el código del alimentador. Dos redes del mismo `.zxst` comparten el mismo lock.

```text
study_lock_key = SHA256(canonical_study_path)
```

El payload obligatorio contendrá:

```json
{
  "database_mdb": "D:\\Bases\\redes.mdb",
  "study_path": "D:\\Estudios\\multi.zxst",
  "feeder_id": "PE104",
  "network_id": "NET_2030_184_PE104",
  "context_fingerprint": "..."
}
```

No se permite una segunda escritura simultánea sobre el mismo estudio. Una lectura que abre CYMDIST también esperará el lock para no observar un estado intermedio.

### 4.2 Ciclo de commit

Toda acción mutante seguirá estas fases:

1. Validar la identidad completa y la pertenencia de `network_id`.
2. Adquirir el lock del estudio.
3. Calcular SHA-256 y tamaño del estudio actual.
4. Crear respaldo previo con timestamp y manifiesto.
5. Abrir la MDB y el estudio por ruta exacta.
6. Confirmar que la red seleccionada existe.
7. Capturar los valores que serán modificados.
8. Ejecutar exclusivamente la mutación solicitada.
9. Releer los valores dentro de la misma sesión.
10. Guardar una sola vez mediante el modo de commit correspondiente.
11. Cerrar sin un segundo guardado.
12. Abrir en un proceso verificador nuevo.
13. Confirmar valores, red, MDB, estudio y presencia de las demás redes.
14. Registrar manifiesto y liberar el lock.

El éxito exige pasos 1–13. Una salida nativa anómala después de escribir un resultado no convierte automáticamente el commit en exitoso: la reapertura y relectura son obligatorias.

### 4.3 Modos de commit

```text
study
study_and_database
external_engine_saved
```

- `study`: `study.Save` para valores del proyecto/estudio.
- `study_and_database`: `study.Save`, `db.Update` y `db.SaveProject` para cabecera o cambios de biblioteca/BD.
- `external_engine_saved`: COM realizó el guardado; RECYM no vuelve a guardar en el mismo proceso y pasa directamente a verificación independiente.

`db.Update` o `SaveProject` no se ejecutarán indiscriminadamente después de cada SpotLoad porque ya se han observado bloqueos en MDB grandes y estudios multi-red.

## 5. Coordinador de persistencia

Se incorporará un componente único, independiente de la interfaz:

```python
commit_cymdist_action(
    action,
    context,
    mutate,
    expected_changes,
    commit_mode,
    timeout_sec,
) -> dict
```

Responsabilidades:

- resolver contexto estricto;
- administrar lock y respaldo;
- ejecutar la mutación en worker aislado;
- impedir doble guardado CymPy/COM;
- lanzar verificador independiente;
- producir manifiesto de commit;
- restaurar el respaldo cuando el guardado falla antes de ser verificable.

Resultado mínimo:

```json
{
  "ok": true,
  "action": "cabecera",
  "context_fingerprint": "...",
  "study_saved": true,
  "db_updated": true,
  "project_saved": true,
  "reopen_verified": true,
  "network_verified": true,
  "neighbor_networks_preserved": true,
  "backup_path": "...",
  "manifest_path": "..."
}
```

## 6. Dos o más alimentadores en un estudio

El estudio compartido es el registro autoritativo. No se crearán copias permanentes por alimentador ni se fusionarán estudios.

Para actualizar A y luego B:

```text
abrir estudio actual → modificar A → commit → verificar A
abrir estudio ya actualizado → modificar B → commit → verificar B y presencia de A
```

El manifiesto del segundo commit incluirá:

- hash anterior, que debe coincidir con el hash posterior del commit de A;
- hash posterior del commit B;
- inventario de redes antes y después;
- red modificada;
- campos verificados;
- ausencia de cambios fuera del alcance declarado cuando estos puedan releerse.

Una discrepancia produce `MULTIFEEDER_STATE_CONFLICT`; no se continúa desde una copia obsoleta.

## 7. Diagnóstico con coloreo real

### 7.1 Diagnóstico 2.1

Después del `NetworkDiagnostic` y LoadFlow diagnóstico:

1. Abrir el modelo real con el contexto exacto.
2. Verificar resultados válidos para el `network_id`.
3. Seleccionar `VoltageLevel` dentro de CYMDIST.
4. Exportar o capturar la vista activa.
5. Seleccionar `LoadingLevel`.
6. Exportar o capturar la vista activa.
7. Restaurar el modo visual previo.
8. Cerrar sin guardar.

Cada imagen requiere sidecar JSON con:

- contexto y huella;
- fecha y escenario;
- motor real utilizado;
- `color_type` exacto;
- método de captura;
- verificación de coloreo;
- SHA-256 del PNG;
- métricas eléctricas relacionadas.

Se rechazan:

- renderizados sintéticos;
- valores proxy o predeterminados;
- capturas de escritorio sin ventana CYMDIST reconocida;
- imágenes antiguas con otra huella;
- `color_verified != true`.

Las capturas de 2.1 son evidencia diagnóstica previa y no sustituyen las capturas situacionales posteriores a 3.3.

## 8. Nuevo paso 3.4

### 8.1 Ubicación y precondiciones

3.4 se mostrará en `Step3Clientes` después de 3.3 y permanecerá deshabilitado hasta que:

- 1.2 tenga commit verificado;
- 3.2 tenga commit verificado;
- 3.3 indique `allocation_ok`, guardado y reapertura verificada;
- el contexto activo no haya cambiado.

### 8.2 Ejecución

3.4 realizará:

1. aplicar escenario situacional sin cargas nuevas;
2. ejecutar LoadFlow real;
3. validar convergencia y resultados numéricos;
4. capturar `VoltageLevel` real;
5. capturar `LoadingLevel` real;
6. verificar ambos PNG y sus sidecars;
7. guardar `loadflow_situacional.json` y el manifiesto de evidencia;
8. actualizar el gate situacional del informe;
9. restaurar modo visual y conexión de cargas al estado previo;
10. cerrar sin persistir cambios temporales del escenario o del coloreo.

El estado situacional representa el modelo distribuido después de 3.3 y antes de incorporar cargas nuevas de §4.

## 9. Renumeración del flujo

La secuencia guiada será:

```text
§1 contexto y cabecera
→ §2 calidad del modelo
→ 3.1 tabla
→ 3.2 EA/Pot
→ 3.3 Load Allocation
→ 3.4 LoadFlow y capturas situacionales
→ §4 cargas nuevas
→ 5.1 LoadFlow proyectado
→ §6 informe
```

- El antiguo 5.1 situacional desaparece de `Step5Flujos`.
- El antiguo 5.2 proyectado se renombra 5.1.
- El flujo general se retira del recorrido principal y queda disponible solo como herramienta técnica, si aún es necesario para compatibilidad.
- Documentación, mensajes de progreso, gates del informe y scripts se actualizarán a la nueva numeración.

## 10. Errores y recuperación

Códigos nuevos o normalizados:

- `STUDY_LOCK_TIMEOUT`
- `NETWORK_NOT_IN_CONTEXT`
- `BACKUP_FAILED`
- `STUDY_SAVE_FAILED`
- `DATABASE_UPDATE_FAILED`
- `PROJECT_SAVE_FAILED`
- `POST_SAVE_REOPEN_FAILED`
- `POST_SAVE_READBACK_MISMATCH`
- `MULTIFEEDER_STATE_CONFLICT`
- `LOADFLOW_NOT_CONVERGED`
- `CYMDIST_COLOR_SELECTION_FAILED`
- `CYMDIST_CAPTURE_NOT_VERIFIED`
- `CONTEXT_IDENTITY_MISMATCH`

Si una mutación falla antes de guardar, se cierra sin guardar. Si el archivo fue guardado pero no supera la relectura, se bloquean pasos posteriores y se ofrece restaurar el respaldo; la restauración no será automática después de un commit parcialmente verificable.

## 11. Evidencia y auditoría

Cada commit escribirá un manifiesto append-only bajo el directorio de salida del alimentador, agrupado por huella de contexto. Incluirá:

- acción y versión de interfaz;
- identidad completa;
- ruta y hash del respaldo;
- hashes del estudio antes y después;
- valores antes, solicitados y releídos;
- modo de commit;
- tiempos de apertura, mutación, guardado y verificación;
- motor CymPy/COM;
- resultado de reapertura;
- lista de redes antes/después;
- warnings o salida nativa anómala.

El informe citará la huella y los manifiestos de 1.2, 3.2, 3.3 y 3.4 utilizados.

## 12. Pruebas

### Unitarias

- clasificación lectura/mutación y modo de commit;
- lock por ruta canónica del estudio;
- rechazo de red ajena;
- una sola llamada de guardado por mutación;
- COM guardado sin segundo `study.Save`;
- verificación de campos y códigos de error;
- detección de hash obsoleto entre alimentadores;
- rechazo de captura no CYMDIST o sin coloreo verificado;
- numeración 3.4/5.1 sin referencias activas a 5.2.

### Integración simulada

- estudio con redes A y B: commit A, commit B, reapertura y conservación de ambas;
- fallo al guardar, al reabrir y al releer;
- diagnóstico restaura parámetros y modo visual;
- 3.4 restaura estado temporal de cargas;
- informe rechaza evidencia de otra huella.

### Integración real CYMDIST

1. Crear respaldo y hashes del fixture aprobado.
2. Ejecutar 1.2 en alimentador A; reabrir y releer P/Q/Vph.
3. Ejecutar 1.2 o 3.2 en alimentador B del mismo estudio; reabrir y verificar A+B.
4. Ejecutar 2.1 y comprobar capturas nativas `VoltageLevel`/`LoadingLevel`.
5. Ejecutar 3.3 y verificar persistencia de la distribución.
6. Ejecutar 3.4 y comprobar LoadFlow situacional y sus dos capturas.
7. Ejecutar 5.1 proyectado después de §4 cuando exista un fixture autorizado.
8. Verificar `/health` después de cada worker.

No se declarará éxito real con mocks, pruebas unitarias o imágenes generadas fuera de CYMDIST.

## 13. Fundamentación

- La tesis doctoral de Puustjärvi sobre workflows transaccionales sustenta la separación de fases y el control de concurrencia en procesos persistentes de larga duración.
- La tesis doctoral de Chkliaev integra bloqueo, recuperación undo/redo y commit, y fundamenta la verificación posterior antes de declarar durabilidad.
- El trabajo indexado sobre atomicidad y procedencia para workflows científicos respalda registrar commit/abort y linaje de cada resultado.
- La tesis doctoral de Fielding respalda que cada solicitud transporte el contexto completo en lugar de depender de estado implícito.
- La revisión sistemática indexada sobre pruebas de aplicaciones web respalda combinar pruebas unitarias, de contrato e integración real.

Referencias:

- Puustjärvi, J. *Transactional Workflows*. PhD Thesis, University of Helsinki, 1999. https://www.cs.helsinki.fi/TR/A-1999/2/
- Chkliaev, D. *Mechanical Verification of Concurrency Control and Recovery Protocols*. PhD Thesis, Eindhoven University of Technology, 2001. https://research.tue.nl/en/publications/mechanical-verification-of-concurrency-control-and-recovery-proto/
- Wang, L., Lu, S., Fei, X., Chebotko, A., Bryant, H. V., Ram, J. L. *Atomicity and provenance support for pipelined scientific workflows*. Future Generation Computer Systems 25(5), 568–576 (2009). https://doi.org/10.1016/j.future.2008.06.007
- Fielding, R. T. *Architectural Styles and the Design of Network-based Software Architectures*. Doctoral dissertation, University of California, Irvine, 2000. https://ics.uci.edu/~fielding/pubs/dissertation/rest_arch_style.htm
- Doğan, S., Betin-Can, A., Garousi, V. *Web application testing: A systematic literature review*. Journal of Systems and Software 91 (2014). https://www.sciencedirect.com/science/article/pii/S0164121214000223
