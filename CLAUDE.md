# Civil 3D Toolkit — Notas de desarrollo

## Entorno confirmado
- Civil 3D 2026
- Dynamo 3.6.1.9956
- Motor Python: **CPython3** (NO IronPython2)
- pythonnet3

## Reglas críticas para la API de Civil 3D en CPython3

### 1. Colecciones — NUNCA usar indexadores `[0]`
```python
# ❌ FALLA con "unindexable object"
estilo = civil_db.Styles.AlignmentStyles[0].ObjectId

# ✅ CORRECTO — usar GetEnumerator()
def _col_first_id(col):
    try:
        e = col.GetEnumerator()
        if e.MoveNext():
            item = e.Current
            return item if hasattr(item, 'IsNull') else getattr(item, 'ObjectId', ObjectId.Null)
    except Exception:
        pass
    return ObjectId.Null
```

### 2. LayerTable — NUNCA usar indexador por nombre
```python
# ❌ FALLA
lt["0"]

# ✅ CORRECTO — iterar con GetEnumerator + lt.Has()
def _get_layer_id(nombre):
    lid = ObjectId.Null
    with db.TransactionManager.StartTransaction() as t:
        lt = t.GetObject(db.LayerTableId, OpenMode.ForRead)
        if not lt.Has(nombre):
            t.Commit()
            return lid
        lt_enum = lt.GetEnumerator()
        while lt_enum.MoveNext():
            ltr_id = lt_enum.Current
            ltr = t.GetObject(ltr_id, OpenMode.ForRead)
            getn = getattr(ltr, 'get_Name', None)
            try:
                nm = getn() if callable(getn) else ""
            except Exception:
                nm = ""
            if nm == nombre:
                lid = ltr_id
                break
        t.Commit()
    return lid
```

### 3. BlockTable / ModelSpace — NUNCA usar indexador
```python
# ❌ FALLA con "unindexable object"
btr = trans.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead)

# ✅ CORRECTO
from Autodesk.AutoCAD.DatabaseServices import SymbolUtilityServices
ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
btr = trans.GetObject(ms_id, OpenMode.ForRead)
```

### 4. Alignment.Create — firma correcta Civil 3D 2026
```python
# ❌ NO EXISTE en C3D 2026
Alignment.Create(civil_db, pline.ObjectId, nombre, ...)

# ✅ CORRECTO — crear vacío + agregar entidades manualmente
# Firma 7-arg confirmada:
Alignment.Create(civil_db, nombre, ObjectId.Null, layer_id, style_id, label_id, AlignmentType.Centerline)
# Fallbacks:
Alignment.Create(civil_db, nombre, ObjectId.Null, layer_id, style_id, label_id)
Alignment.Create(civil_db, nombre, "", "0", "Basic", "")
```

### 5. Profile.CreateFromSurface — firma correcta
```python
# ✅ Firma confirmada (nombre, alignId, surfId, layerId, styleId, labelId)
Profile.CreateFromSurface(nombre, ali.ObjectId, sup.ObjectId, layer_id, style_id, label_id)
```

### 6. ProfileView.Create — primer arg es alignmentId (ObjectId), no civil_db
```python
# ❌ FALLA
ProfileView.Create(civil_db, nombre, ali.ObjectId, pt, style)

# ✅ CORRECTO
ProfileView.Create(ali.ObjectId, pt, nombre, band_id, style_id)
ProfileView.Create(ali.ObjectId, pt, nombre, style_id)
ProfileView.Create(ali.ObjectId, pt, nombre)
```

### 7. TinSurface.Create — usar db (Database), no civil_db
```python
# ❌ FALLA
TinSurface.Create(civil_db, nombre)

# ✅ CORRECTO
TinSurface.Create(db, nombre)
```

### 8. Atributos que NO existen en C3D 2026
- `TinSurface.FindMinimumElevation()` → usar `SurfaceProperties.MinimumElevation` o try/except
- `TinSurface.NumberOfTriangles` → usar `Triangles.Count` o try/except
- `Alignment.GeomExtents` → usar `first_attr(ali, ['GeomExtents','Extents','Bounds'])`
- `AlignmentCreationOptions` → no existe, importar con try/except
- `AlignmentType` → importar con try/except (puede no estar en todos los builds)

### 9. OUT del nodo Python — NO devolver dict
```python
# ❌ Dynamo 3.x lanza "Dictionary.ByKeysValues key empty"
OUT = [mi_dict, mi_lista]

# ✅ CORRECTO — devolver string
OUT = '\n'.join(log)
```

### 10. Patrón try_attempts para múltiples firmas
```python
def try_attempts(attempts, label):
    errores = []
    for obj, name, args in attempts:
        method = getattr(obj, name, None)
        if method is None:
            errores.append(f"{name}: no existe")
            continue
        try:
            return method(*args)
        except Exception as ex:
            errores.append(f"{name}({len(args)} args): {ex}")
    raise Exception(f"Fallo {label}:\n    - " + '\n    - '.join(errores))
```

## Formato del conector en .dyn (Dynamo 3.6)
```json
{
  "Start": "puerto_guid_salida",
  "End":   "puerto_guid_entrada",
  "Id":    "nuevo_uuid",
  "IsHidden": "False"
}
```
- `Start`/`End` son GUIDs de **puertos**, NO de nodos
- Sin `StartIndex`/`EndIndex` (eso es formato Dynamo 2.x)

## Nodo Python en .dyn (Dynamo 3.6)
```json
{
  "Engine": "CPython3",
  "VariableInputPorts": true,
  "Code": "...",
  "NodeType": "PythonScriptNode"
}
```
- Campo del script: `"Code"` (NO `"Script"` que es Dynamo 2.x)
- Engine: `"CPython3"` (NO `"IronPython2"`)

## Archivo de referencia funcional
`AutomatizacionParqueEolico.dyn` — subido por el usuario, contiene todos los
patrones correctos probados en Civil 3D 2026 / Dynamo 3.6.
