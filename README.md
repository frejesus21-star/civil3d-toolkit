[README.md](https://github.com/user-attachments/files/27658274/README.md)
# Civil 3D Dynamo Toolkit 🛣️

Automatización vial completa para **Autodesk Civil 3D 2018 → 2026** usando Dynamo y LISP.

## Estructura del repositorio

```
civil3d-toolkit/
├── C3D_Toolkit_EjeDeCamino.dyn   ← Grafo Dynamo — abrir directamente
├── dynamo/
│   ├── 00_Alineamiento_desde_EjeCamino.py    ← Polilínea → Alineamiento
│   ├── 01_Corredor_camino.py                 ← Corredor con ensamble "camino"
│   ├── 02_Desbroce_desde_TN.py               ← SDESBROCE = TN − delta
│   ├── 04_VistaPerfil_TN_Desbroce_Rasante.py ← Vista perfil longitudinal
│   └── c3d_compat.py                         ← Wrapper compatibilidad 2018-2026
└── lisp/
    └── civil3d-toolkit.lsp                   ← 6 comandos complementarios
```

## Nombres fijos del proyecto

| Elemento | Nombre en Civil 3D |
|---|---|
| Capa del eje | `EJE DE CAMINO` |
| Superficie terreno | `TN` |
| Superficie desbroce | `SDESBROCE` |
| Ensamble | `camino` |

## Cómo usar el grafo `.dyn`

1. Abrir Dynamo desde Civil 3D
2. `File → Open` → seleccionar `C3D_Toolkit_EjeDeCamino.dyn`
3. Ajustar los valores de entrada (cuadros amarillos)
4. Correr en orden: **00 → 02 → 01 → 04**
5. Revisar el nodo **log** de cada módulo para verificar resultados

## Orden de ejecución

```
Polilínea en capa "EJE DE CAMINO"
        ↓
[00] Alineamiento  →  Civil 3D crea el alineamiento con arcos y tangentes
        ↓
[02] Desbroce      →  SDESBROCE = TN − delta (cm de descapote)
        ↓
[01] Corredor      →  Corredor con ensamble "camino" sobre TN
        ↓
[04] Vista perfil  →  TN · SDESBROCE · RASANTE — a la derecha del eje
```

## Parámetros de entrada

### Módulo 00 — Alineamiento
| Input | Tipo | Ejemplo |
|---|---|---|
| `nombre_alineamiento` | String | `"EJE PRINCIPAL"` |
| `capa_polilinea` | String | `"EJE DE CAMINO"` |
| `estacion_inicio` | Number | `0.0` |
| `sobrescribir` | Bool | `True` |

### Módulo 02 — Desbroce
| Input | Tipo | Ejemplo |
|---|---|---|
| `delta_desbroce` | Number | `0.30` (= 30 cm) |
| `sobrescribir` | Bool | `True` |

> El delta **siempre se resta** — el desbroce es extracción de capa vegetal, siempre hacia abajo.

### Módulo 01 — Corredor
| Input | Tipo | Ejemplo |
|---|---|---|
| `nombre_alineamiento` | String | `"EJE PRINCIPAL"` |
| `nombre_rasante` | String | `"RASANTE"` |
| `pendiente_max` | Number | `12.0` |
| `intervalo_muestreo` | Number | `5.0` |
| `sobrescribir` | Bool | `True` |

### Módulo 04 — Vista de perfil
| Input | Tipo | Ejemplo |
|---|---|---|
| `nombre_alineamiento` | String | `"EJE PRINCIPAL"` |
| `nombre_rasante` | String | `"RASANTE"` |
| `escala_h` | Number | `1000` |
| `escala_v` | Number | `100` |
| `offset_derecha` | Number | `0` (auto) |

## Comandos LISP

Cargar en AutoCAD: `(load "ruta/lisp/civil3d-toolkit.lsp")`

| Comando | Función |
|---|---|
| `C3D-SUPERFICIE-INFO` | Info completa de una superficie |
| `C3D-EXPORTAR-PVTS` | Exportar PVIs de rasante → CSV |
| `C3D-BATCH-REBUILD` | Reconstruir todas las superficies |
| `C3D-ESTACIONES-CRITICAS` | Marcar estaciones con pendiente > máx. |
| `C3D-CORREGIR-COSTURA` | Reparar puntos de costura defectuosos |
| `C3D-LIMPIEZA-TIN` | Eliminar triángulos espurios del TIN |

## Compatibilidad

- Civil 3D 2018 → 2026
- Dynamo 2.x / 3.x
- Motor Python: CPython3 / PythonNet3

## Notas importantes

- La polilínea del eje debe ser `Polyline` (LWPolyline) o `Polyline2D` — no `Polyline3D`.
- Si hay más de una polilínea en la capa `EJE DE CAMINO`, el módulo 00 usa la más larga.
- El módulo 04 calcula el offset automáticamente si se deja en `0`.
