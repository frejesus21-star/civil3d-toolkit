"""
╔══════════════════════════════════════════════════════════════════════╗
║   C3D_COMPAT.PY — Wrapper de compatibilidad multi-versión           ║
║   Civil 3D 2018 · 2019 · 2020 · 2021 · 2022 · 2023 · 2024 · 2025 · 2026
║                                                                      ║
║   USO: Pegar este bloque al INICIO de cualquier nodo Python          ║
║        de Dynamo para garantizar compatibilidad.                     ║
╚══════════════════════════════════════════════════════════════════════╝

INSTRUCCIÓN DE USO:
  En cada nodo Python de Dynamo, reemplaza los imports manuales por:

    exec(open(r"C:\ruta\a\c3d_compat.py").read())

  O simplemente copia el bloque "BLOQUE COPIABLE" al inicio de tu nodo.
"""

# ════════════════════════════════════════════════════════════════════
# BLOQUE COPIABLE — pegar al inicio de cualquier nodo Python Dynamo
# ════════════════════════════════════════════════════════════════════

import clr, sys

# ── Carga de DLLs (orden de compatibilidad 2018-2026) ────────────────
_dlls = [
    'AeccDbMgd',           # Civil 3D principal (todas las versiones)
    'AeccPressurePipesMgd',# Redes a presión (opcional, 2020+)
    'AcMgd',               # AutoCAD managed
    'AcCoreMgd',           # AutoCAD Core (2013+)
    'AcDbMgd',             # AutoCAD DB
]
for _dll in _dlls:
    try:
        clr.AddReference(_dll)
    except:
        pass  # Si no está disponible en esta versión, se omite

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    Transaction, OpenMode, ObjectId
)
from Autodesk.AutoCAD.Geometry import Point3d, Point2d

from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import (
    TinSurface,
    Alignment,
    Profile,
    Corridor,
)

# ── Imports opcionales según versión ────────────────────────────────
# ProfileView existe desde C3D 2018 pero la firma de Create cambió en 2020
try:
    from Autodesk.Civil.DatabaseServices import ProfileView
    _HAS_PROFILEVIEW = True
except:
    _HAS_PROFILEVIEW = False

# SampleLine / SectionView — disponibles en todas, API estable desde 2019
try:
    from Autodesk.Civil.DatabaseServices import (
        SampleLine, SampleLineGroup, SectionView
    )
    _HAS_SECTIONS = True
except:
    _HAS_SECTIONS = False

# FeatureLine — C3D 2018+
try:
    from Autodesk.Civil.DatabaseServices import FeatureLine
    _HAS_FEATURELINE = True
except:
    _HAS_FEATURELINE = False

# ── Detección de versión del producto ───────────────────────────────
def get_c3d_version():
    """
    Retorna el año de versión de Civil 3D como int (ej: 2024).
    Usa el número de versión interno de AutoCAD.
    """
    try:
        ver_str = Application.Version   # ej: "24.1.55.0" para 2024
        major   = int(ver_str.split('.')[0])
        # Mapeo internal → año de producto
        _map = {
            22:2018, 23:2019, 24:2020, 25:2021,
            26:2022, 27:2023, 28:2024, 29:2025, 30:2026
        }
        return _map.get(major, major)
    except:
        return 0

C3D_VERSION = get_c3d_version()

# ── Acceso al documento activo ───────────────────────────────────────
doc      = Application.DocumentManager.MdiActiveDocument
db       = doc.Database
civil_db = CivilApplication.ActiveDocument

# ── Helper: obtener superficie por nombre ────────────────────────────
def c3d_get_surface(nombre, trans, modo=OpenMode.ForRead):
    """Busca una superficie por nombre. Compatible con todas las versiones."""
    for oid in civil_db.GetSurfaceIds():
        obj = trans.GetObject(oid, modo)
        if hasattr(obj, 'Name') and obj.Name == nombre:
            return obj
    return None

# ── Helper: obtener alineamiento por nombre ──────────────────────────
def c3d_get_alignment(nombre, trans, modo=OpenMode.ForRead):
    for oid in civil_db.GetAlignmentIds():
        obj = trans.GetObject(oid, modo)
        if hasattr(obj, 'Name') and obj.Name == nombre:
            return obj
    return None

# ── Helper: crear superficie TIN vacía (firma compatible) ────────────
def c3d_create_tin(nombre, descripcion, trans):
    """
    Crea TinSurface. Prueba las firmas de cada versión en orden.
    """
    try:
        # Firma 2020+ (con estilo)
        eid = civil_db.Styles.SurfaceStyles[0].ObjectId
        sid = TinSurface.Create(civil_db, nombre, eid)
    except:
        try:
            # Firma 2018-2019 (sin estilo)
            sid = TinSurface.Create(civil_db, nombre)
        except Exception as e:
            return None, str(e)
    sup = trans.GetObject(sid, OpenMode.ForWrite)
    sup.Description = descripcion
    return sup, None

# ── INFO al cargar ───────────────────────────────────────────────────
_info = f"[C3D COMPAT] Versión detectada: Civil 3D {C3D_VERSION}"
_info += f" | ProfileView: {'OK' if _HAS_PROFILEVIEW else 'N/A'}"
_info += f" | Sections: {'OK' if _HAS_SECTIONS else 'N/A'}"
# ════════════════════════════════════════════════════════════════════
# FIN DEL BLOQUE COPIABLE
# ════════════════════════════════════════════════════════════════════
