"""
╔══════════════════════════════════════════════════════════════════════╗
║   VISTA DE PERFIL LONGITUDINAL — Dynamo para Civil 3D               ║
║   Perfiles: TN · SDESBROCE · RASANTE                                ║
║   Posición:  a la derecha del alineamiento en plano                 ║
║   Compatible: Civil 3D 2018 → 2026                                  ║
╚══════════════════════════════════════════════════════════════════════╝

DESCRIPCIÓN:
  Crea la vista de perfil longitudinal que muestra los tres perfiles:
    · Perfil de terreno natural   → extraído de la superficie "TN"
    · Perfil de desbroce          → extraído de la superficie "SDESBROCE"
    · Perfil de rasante           → perfil de diseño ya existente

  La vista se inserta automáticamente a la derecha del alineamiento
  en el espacio modelo, con un offset configurable.

INPUTS (nodos Dynamo):
  - nombre_alineamiento : str   → nombre del alineamiento
  - nombre_rasante      : str   → nombre del perfil de rasante de diseño
  - escala_h            : float → escala horizontal (ej: 1000 → 1:1000)
  - escala_v            : float → escala vertical   (ej: 100  → 1:100)
  - offset_derecha      : float → separación en metros desde el eje al borde
                                  de la vista. Si no se da, se calcula auto.

OUTPUTS:
  - vista_perfil_id → ObjectId de la vista creada
  - punto_insercion → Point3d donde se insertó la vista
  - log             → mensajes del proceso

NOMBRES FIJOS:
  - Superficie TN       : "TN"
  - Superficie desbroce : "SDESBROCE"
"""

import clr
import math

clr.AddReference('AeccDbMgd')
clr.AddReference('AcMgd')
clr.AddReference('AcCoreMgd')
clr.AddReference('AcDbMgd')

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    Transaction, OpenMode, ObjectId
)
from Autodesk.AutoCAD.Geometry import Point3d, Point2d, Extents3d

from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import (
    Alignment, Profile, ProfileView, TinSurface
)

doc      = Application.DocumentManager.MdiActiveDocument
db       = doc.Database
civil_db = CivilApplication.ActiveDocument
log      = []

# ── Nombres fijos ────────────────────────────────────────────────────
NOMBRE_TN        = "TN"
NOMBRE_DESBROCE  = "SDESBROCE"

# ── Defaults de inputs ───────────────────────────────────────────────
try:    _ali_nombre   = str(nombre_alineamiento).strip()
except: _ali_nombre   = "EJE PRINCIPAL"

try:    _ras_nombre   = str(nombre_rasante).strip()
except: _ras_nombre   = "RASANTE"

try:    _esc_h = float(escala_h)
except: _esc_h = 1000.0

try:    _esc_v = float(escala_v)
except: _esc_v = 100.0

try:    _offset = float(offset_derecha)
except: _offset = None   # se calcula automáticamente


def get_alignment(nombre, trans):
    for oid in civil_db.GetAlignmentIds():
        o = trans.GetObject(oid, OpenMode.ForRead)
        if hasattr(o, 'Name') and o.Name == nombre:
            return o
    return None


def get_surface(nombre, trans):
    for oid in civil_db.GetSurfaceIds():
        o = trans.GetObject(oid, OpenMode.ForRead)
        if hasattr(o, 'Name') and o.Name == nombre:
            return o
    return None


def get_or_create_profile_from_surface(ali, superficie, prefijo, trans):
    """
    Busca un perfil de terreno para 'ali' extraído de 'superficie'.
    Si no existe, lo crea con Profile.CreateFromSurface().
    Nombre del perfil = prefijo + "_" + nombre superficie.
    """
    nombre_perfil = f"{prefijo}_{superficie.Name}"

    # ¿Ya existe?
    try:
        for pid in ali.GetProfileIds():
            p = trans.GetObject(pid, OpenMode.ForRead)
            if hasattr(p, 'Name') and p.Name == nombre_perfil:
                log.append(f"[INFO] Perfil '{nombre_perfil}' ya existe. Reutilizando.")
                return p
    except Exception as e:
        log.append(f"[WARN] buscando perfil '{nombre_perfil}': {e}")

    # Crear desde superficie
    try:
        estilo_id  = civil_db.Styles.ProfileStyles[0].ObjectId
        label_id   = civil_db.Styles.LabelSetStyles.ProfileLabelSetStyles[0].ObjectId

        pid = Profile.CreateFromSurface(
            nombre_perfil,
            ali.ObjectId,
            superficie.ObjectId,
            estilo_id,
            label_id
        )
        p = trans.GetObject(pid, OpenMode.ForRead)
        log.append(f"[OK]  Perfil '{nombre_perfil}' creado desde superficie '{superficie.Name}'.")
        return p
    except Exception as e:
        log.append(f"[ERROR] creando perfil desde superficie '{superficie.Name}': {e}")
        return None


def get_profile_by_name(ali, nombre, trans):
    """Busca perfil por nombre dentro del alineamiento."""
    try:
        for pid in ali.GetProfileIds():
            p = trans.GetObject(pid, OpenMode.ForRead)
            if hasattr(p, 'Name') and p.Name == nombre:
                return p
    except Exception as e:
        log.append(f"[WARN] buscando perfil '{nombre}': {e}")
    return None


def calcular_punto_insercion_derecha(ali, offset, trans):
    """
    Calcula el punto de inserción de la vista de perfil a la derecha
    del alineamiento.

    Estrategia:
      1. Obtiene el bounding box del alineamiento en plano (XY).
      2. Toma el extremo derecho (max X) y le suma el offset.
      3. Usa la Y media del alineamiento para centrar verticalmente.
    """
    try:
        # Bounding box del alineamiento
        ext = ali.GeomExtents   # Extents3d con MinPoint y MaxPoint
        x_max = ext.MaxPoint.X
        y_mid = (ext.MinPoint.Y + ext.MaxPoint.Y) / 2.0

        # Si no se pasó offset, se estima según la longitud del alineamiento
        if offset is None:
            # Regla práctica: 10% de la longitud del alineamiento + 50m mínimo
            _off = max(ali.Length * 0.10, 50.0)
            log.append(f"[INFO] Offset calculado automáticamente: {_off:.1f} m")
        else:
            _off = float(offset)

        pt = Point3d(x_max + _off, y_mid, 0.0)
        log.append(
            f"[INFO] Punto de inserción vista: "
            f"X={pt.X:.2f}, Y={pt.Y:.2f} "
            f"(derecha del alineamiento, offset {_off:.1f} m)"
        )
        return pt

    except Exception as e:
        log.append(f"[WARN] calculando punto de inserción: {e}. Usando origen (0,0,0).")
        return Point3d(0, 0, 0)


def crear_vista_perfil(ali, perfiles, punto_ins, trans):
    """
    Crea la vista de perfil con los tres perfiles.
    Compatible con la firma de ProfileView.Create de C3D 2018-2026.
    """
    nombre_vista = f"PL_{ali.Name}"

    # Verificar si ya existe
    try:
        for pvid in ali.GetProfileViewIds():
            pv = trans.GetObject(pvid, OpenMode.ForRead)
            if hasattr(pv, 'Name') and pv.Name == nombre_vista:
                log.append(f"[INFO] Vista '{nombre_vista}' ya existe. Actualizando perfiles.")
                pv_w = trans.GetObject(pvid, OpenMode.ForWrite)
                for p in perfiles:
                    if p:
                        try:
                            pv_w.AddProfile(p.ObjectId)
                        except:
                            pass  # ya estaba agregado
                return pvid, punto_ins
    except Exception as e:
        log.append(f"[WARN] buscando vista existente: {e}")

    # Crear nueva vista
    try:
        estilo_pv_id = civil_db.Styles.ProfileViewStyles[0].ObjectId

        # Firma completa C3D 2020+
        try:
            from Autodesk.Civil.DatabaseServices import ProfileViewOptions
            opciones = ProfileViewOptions()
            opciones.DrawElevationGridlines = True

            pv_id = ProfileView.Create(
                civil_db,
                nombre_vista,
                ali.ObjectId,
                punto_ins,
                estilo_pv_id,
                opciones
            )
        except:
            # Firma simplificada C3D 2018-2019
            pv_id = ProfileView.Create(
                civil_db,
                nombre_vista,
                ali.ObjectId,
                punto_ins,
                estilo_pv_id
            )

        pv = trans.GetObject(pv_id, OpenMode.ForWrite)

        # Agregar los tres perfiles: TN, SDESBROCE, RASANTE
        estilos_perfil = civil_db.Styles.ProfileStyles
        for i, perfil in enumerate(perfiles):
            if perfil is None:
                continue
            try:
                # Asignar estilo diferenciado por tipo
                # 0=terreno, 1=diseño — ajusta los índices según tu plantilla
                estilo_idx = 0 if i < 2 else 1
                est_id = estilos_perfil[min(estilo_idx, estilos_perfil.Count - 1)].ObjectId
                pv.AddProfile(perfil.ObjectId, est_id)
                log.append(f"[OK]  Perfil '{perfil.Name}' agregado a la vista.")
            except:
                try:
                    # Fallback sin estilo
                    pv.AddProfile(perfil.ObjectId)
                    log.append(f"[OK]  Perfil '{perfil.Name}' agregado (sin estilo).")
                except Exception as e2:
                    log.append(f"[WARN] no se pudo agregar '{perfil.Name}': {e2}")

        log.append(f"[OK]  Vista '{nombre_vista}' creada a la derecha del alineamiento.")
        return pv_id, punto_ins

    except Exception as e:
        log.append(f"[ERROR] creando vista de perfil: {e}")
        return None, punto_ins


# ── EJECUCIÓN PRINCIPAL ──────────────────────────────────────────────
vista_perfil_id = None
punto_insercion = None

with doc.LockDocument():
    with db.TransactionManager.StartTransaction() as trans:
        try:
            ali       = get_alignment(_ali_nombre, trans)
            sup_tn    = get_surface(NOMBRE_TN,       trans)
            sup_desb  = get_surface(NOMBRE_DESBROCE,  trans)

            if not ali:
                log.append(f"[ERROR] Alineamiento '{_ali_nombre}' no encontrado.")
            else:
                # ── Perfil TN ────────────────────────────────────────
                if sup_tn:
                    perf_tn = get_or_create_profile_from_surface(
                        ali, sup_tn, "TN", trans
                    )
                else:
                    log.append(f"[WARN] Superficie '{NOMBRE_TN}' no encontrada. Perfil TN omitido.")
                    perf_tn = None

                # ── Perfil SDESBROCE ─────────────────────────────────
                if sup_desb:
                    perf_desb = get_or_create_profile_from_surface(
                        ali, sup_desb, "SD", trans
                    )
                else:
                    log.append(f"[WARN] Superficie '{NOMBRE_DESBROCE}' no encontrada. Perfil desbroce omitido.")
                    perf_desb = None

                # ── Perfil RASANTE ───────────────────────────────────
                perf_ras = get_profile_by_name(ali, _ras_nombre, trans)
                if not perf_ras:
                    log.append(
                        f"[WARN] Perfil de rasante '{_ras_nombre}' no encontrado. "
                        f"La vista se creará sin rasante — agrégala después."
                    )

                # ── Punto de inserción (derecha del alineamiento) ────
                pt_ins = calcular_punto_insercion_derecha(ali, _offset, trans)

                # ── Crear vista con los tres perfiles ────────────────
                vista_perfil_id, punto_insercion = crear_vista_perfil(
                    ali,
                    [perf_tn, perf_desb, perf_ras],   # orden: TN, DESBROCE, RASANTE
                    pt_ins,
                    trans
                )

                if vista_perfil_id:
                    trans.Commit()
                    resumen = []
                    if perf_tn:   resumen.append("TN")
                    if perf_desb: resumen.append("SDESBROCE")
                    if perf_ras:  resumen.append("RASANTE")
                    log.append(
                        f"[✓] Vista de perfil lista con: {' · '.join(resumen)}. "
                        f"Ubicada a la derecha del alineamiento."
                    )
                else:
                    trans.Abort()

        except Exception as e:
            log.append(f"[ERROR CRÍTICO] {e}")
            trans.Abort()

OUT = [vista_perfil_id, punto_insercion, log]
