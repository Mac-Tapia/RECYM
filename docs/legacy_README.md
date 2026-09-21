# CYMDIST PA217 - Corrección masiva con CymPy

Proyecto para VS Code / Cursor orientado a CYME/CYMDIST 9.2 R1.

## Objetivo
Corregir masivamente, por ID, elementos importados del alimentador PA217:
- nodos con tensión base incompatible (220052),
- líneas aéreas/cables/seccionadores en `Predeterminado` (220047),
- catálogos de equipos incompletos,
- auditoría antes/después.

## Regla de seguridad
**El proyecto arranca en `DRY_RUN = true`.**
No modifica CYMDIST hasta que:
1. `check_environment.py` confirme Python/CymPy.
2. `inspect_cympy.py` obtenga los nombres internos reales de CYME 9.2 R1.
3. Se complete `config/cympy_fields.json`.
4. Los catálogos de equipos sean validados.

## Python correcto
Usar:
`C:\Program Files (x86)\CYME\CYME\Python37\python.exe`

No ejecutar desde ChatGPT/Pyodide, Colab o Python 3.11.

## Orden recomendado
1. Ejecutar `scripts\01_check_environment.bat`
2. Ejecutar `scripts\02_inspect_cympy.bat`
3. Completar `config\cympy_fields.json`
4. Completar `data\input\PA217_Catalogo_Maestro.xlsx`
5. Ejecutar `scripts\03_validate_excel.bat`
6. Ejecutar `scripts\04_dry_run.bat`
7. Revisar `data\output\preview_changes.csv`
8. Cambiar `"dry_run": false` en `config/settings.json`
9. Ejecutar `scripts\05_apply_changes.bat`
10. Volver a correr Herramienta Diagnóstica en CYMDIST.

## Importante
Los nombres de `DeviceType` y de campos CymPy cambian entre versiones.
Este proyecto **no inventa esos nombres**: primero los descubre localmente.
