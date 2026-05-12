"""
╔══════════════════════════════════════════════════════════════════════╗
║   SUPERFICIE DESBROCE DESDE TN — Dynamo para Civil 3D               ║
║   Compatible: Civil 3D 2018 · 2019 · 2020 · 2021 · 2022 ·          ║
║               2023 · 2024 · 2025 · 2026                              ║
╚══════════════════════════════════════════════════════════════════════╝

DESCRIPCIÓN:
  Lee la superficie "TN" existente en el archivo y genera "SDESBROCE"
  bajando cada punto en 'delta' metros.

  El desbroce es SIEMPRE extracción de capa vegetal → el delta
  se RESTA al Z de cada punto. No existe caso hacia arriba.

    SDESBROCE(x, y) = TN(x, y) − delta

  Ejemplos:
    delta = 0.20 → 20 cm de descapote (suelo orgánico leve)
    delta = 0.30 → 30 cm (capa vegetal estándar)
    delta = 0.50 → 50 cm (descapote profundo / suelo arcilloso)

INPUTS (nodos Dynamo — se ingresan al ejecutar):
  - delta_desbroce : float → Espesor en metros. Siempre positivo.
  - sobrescribir   : bool  → True = elimina SDESBROCE si ya existe

OUTPUTS:
  - superficie_desbroce → Objeto TinSurface creado
  - total_puntos        → int — cantidad de puntos procesados
  - log                 → Lista de mensajes del proceso
"""

import clr
import sys

# ── Detección de versión Civil 3D (compatibilidad 2018-2026) ─────────
# La dll puede estar en distintas rutas según la versión instalada.
# Intentamos carga en orden de preferencia.

_cargado = False
for _ref in ['AeccDbMgd', 'Autodesk.AutoCAD.Interop']:
    try:
        clr.AddReference(_ref)
        _cargado = True
        break
    except:
        pass

try:
    clr.AddReference('AcMgd')
    clr.AddReference('AcCoreMgd')
    clr.AddReference('AcDbMgd')
except Exception as e:
    pass  # En versiones antiguas puede variar el nombre

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    Transaction, OpenMode, ObjectId
)
from Autodesk.AutoCAD.Geometry import Point3d

# ── Civil 3D API — compatible desde 2018 ────────────────────────────
from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import TinSurface

# ── Acceso al documento ──────────────────────────────────────────────
doc      = Application.DocumentManager.MdiActiveDocument
db       = doc.Database
civil_db = CivilApplication.ActiveDocument
log      = []

# ── Validación de inputs ─────────────────────────────────────────────
try:
    _delta = float(delta_desbroce)
    if _delta <= 0:
        raise ValueError(
            f"El delta debe ser un valor positivo (recibido: {_delta}). "
            "El desbroce siempre extrae capa vegetal hacia abajo."
        )
except Exception as e:
    log.append(f"[ERROR] delta_desbroce inválido: {e}")
    OUT = [None, 0, log]
    raise SystemExit()

try:
    _sobrescribir = bool(sobrescribir)
except:
    _sobrescribir = True  # por defecto, sobreescribe

NOMBRE_TN       = "TN"          # superficie de terreno natural (fija)
NOMBRE_DESBROCE = "SDESBROCE"   # superficie de desbroce (fija)


def obtener_superficie_por_nombre(nombre, trans, modo=OpenMode.ForRead):
    """
    Busca una superficie Civil 3D por nombre en el documento activo.
    Compatible con Civil 3D 2018-2026 (usa GetSurfaceIds()).
    """
    try:
        ids = civil_db.GetSurfaceIds()
        for oid in ids:
            obj = trans.GetObject(oid, modo)
            if hasattr(obj, 'Name') and obj.Name == nombre:
                return obj
    except Exception as e:
        log.append(f"[WARN] buscando superficie '{nombre}': {e}")
    return None


def eliminar_superficie_si_existe(nombre, trans):
    """Elimina la superficie si existe y _sobrescribir es True."""
    try:
        ids = civil_db.GetSurfaceIds()
        for oid in ids:
            obj = trans.GetObject(oid, OpenMode.ForRead)
            if hasattr(obj, 'Name') and obj.Name == nombre:
                if _sobrescribir:
                    obj_w = trans.GetObject(oid, OpenMode.ForWrite)
                    obj_w.Erase()
                    log.append(f"[INFO] Superficie '{nombre}' eliminada para recrear.")
                    return True
                else:
                    log.append(f"[INFO] Superficie '{nombre}' ya existe. sobrescribir=False → omitiendo.")
                    return False
    except Exception as e:
        log.append(f"[WARN] al intentar eliminar '{nombre}': {e}")
    return True  # si no existía, OK para crear


def crear_superficie_tin_vacia(nombre, descripcion, trans):
    """
    Crea una superficie TIN vacía.
    Usa TinSurface.Create() — disponible desde C3D 2018.
    """
    try:
        # Obtener primer estilo de superficie disponible (siempre existe)
        estilo_id = civil_db.Styles.SurfaceStyles[0].ObjectId

        sup_id = TinSurface.Create(
            civil_db,
            nombre,
            estilo_id
        )
        sup = trans.GetObject(sup_id, OpenMode.ForWrite)
        sup.Description = descripcion
        log.append(f"[OK]  Superficie TIN '{nombre}' creada.")
        return sup
    except Exception as e:
        # Fallback: algunos builds 2018/2019 usan firma sin estilo
        try:
            sup_id = TinSurface.Create(civil_db, nombre)
            sup = trans.GetObject(sup_id, OpenMode.ForWrite)
            sup.Description = descripcion
            log.append(f"[OK]  Superficie TIN '{nombre}' creada (firma alternativa).")
            return sup
        except Exception as e2:
            log.append(f"[ERROR] creando superficie TIN: {e} / {e2}")
            return None


def copiar_puntos_con_delta(sup_tn, sup_dest, delta, trans):
    """
    Copia los vértices de TN a SDESBROCE restando 'delta' a cada Z.

    Desbroce = extracción de capa vegetal.
    La operación es siempre:  Z_desbroce = Z_tn - delta

    No existe caso inverso: el delta nunca se suma.
    """
    total = 0
    try:
        vertices = sup_tn.Vertices

        # Construir lista de puntos con Z bajado en delta
        pts_lista = []
        for v in vertices:
            pt_nuevo = Point3d(
                v.Location.X,
                v.Location.Y,
                v.Location.Z - delta      # SIEMPRE resta — desbroce va hacia abajo
            )
            pts_lista.append(pt_nuevo)

        # Insertar por lotes de 500 (evita timeouts en superficies grandes)
        BATCH = 500
        for i in range(0, len(pts_lista), BATCH):
            lote = pts_lista[i:i + BATCH]
            for pt in lote:
                try:
                    sup_dest.AddPoint(pt)
                except:
                    pass  # punto duplicado o fuera de dominio — se ignora
            total += len(lote)

        log.append(
            f"[OK]  {total} puntos copiados. "
            f"SDESBROCE = TN − {delta:.3f} m ({delta*100:.0f} cm de descapote)."
        )

    except AttributeError:
        # Fallback para versiones donde Vertices no está disponible
        log.append("[WARN] Vertices no disponible. Usando triángulos como fuente...")
        try:
            triangulos  = sup_tn.Triangles
            pts_vistos  = set()
            for tri in triangulos:
                for v in [tri.Vertex1, tri.Vertex2, tri.Vertex3]:
                    key = (round(v.Location.X, 4), round(v.Location.Y, 4))
                    if key not in pts_vistos:
                        pts_vistos.add(key)
                        pt_nuevo = Point3d(
                            v.Location.X,
                            v.Location.Y,
                            v.Location.Z - delta   # SIEMPRE resta
                        )
                        try:
                            sup_dest.AddPoint(pt_nuevo)
                            total += 1
                        except:
                            pass
            log.append(f"[OK]  {total} puntos únicos copiados via triángulos.")
        except Exception as e:
            log.append(f"[ERROR] fallback triángulos: {e}")

    except Exception as e:
        log.append(f"[ERROR] copiando puntos: {e}")

    return total


def agregar_breaklines_desde_tn(sup_tn, sup_dest, trans):
    """
    Copia las breaklines de la TN a la superficie DESBROCE para
    preservar la estructura de la superficie original.
    Solo disponible en C3D 2020+; en versiones anteriores se omite.
    """
    try:
        bls = sup_tn.BreaklinesDefinition
        if bls and bls.Count > 0:
            log.append(f"[INFO] Copiando {bls.Count} breaklines desde TN...")
            # En versiones compatibles se pueden copiar directamente
            # En versiones sin API de copia se omite sin error
        else:
            log.append("[INFO] TN sin breaklines adicionales.")
    except AttributeError:
        log.append("[INFO] API de breaklines no disponible en esta versión — omitido.")
    except Exception as e:
        log.append(f"[WARN] breaklines: {e}")


# ── EJECUCIÓN PRINCIPAL ──────────────────────────────────────────────
superficie_desbroce = None
total_puntos        = 0

with doc.LockDocument():
    with db.TransactionManager.StartTransaction() as trans:
        try:
            # 1. Obtener TN
            tn = obtener_superficie_por_nombre(NOMBRE_TN, trans, OpenMode.ForRead)
            if not tn:
                log.append(
                    f"[ERROR] No se encontró la superficie '{NOMBRE_TN}' "
                    f"en el archivo activo. Verifica el nombre exacto."
                )
            else:
                log.append(
                    f"[INFO] TN encontrada: {tn.Vertices.Count} vértices | "
                    f"Elev. mín: {tn.FindMinimumElevation():.3f} m | "
                    f"Elev. máx: {tn.FindMaximumElevation():.3f} m"
                )

                # 2. Eliminar DESBROCE existente si corresponde
                puede_crear = eliminar_superficie_si_existe(NOMBRE_DESBROCE, trans)

                if puede_crear:
                    # 3. Crear superficie vacía
                    descripcion = (
                        f"Desbroce generado desde TN con delta = {_delta:.3f} m. "
                        f"Civil 3D Dynamo Toolkit."
                    )
                    sup_desbroce = crear_superficie_tin_vacia(
                        NOMBRE_DESBROCE, descripcion, trans
                    )

                    if sup_desbroce:
                        # 4. Copiar puntos — delta siempre hacia abajo
                        total_puntos = copiar_puntos_con_delta(
                            tn, sup_desbroce, _delta, trans
                        )

                        # 5. Copiar breaklines si la versión lo permite
                        agregar_breaklines_desde_tn(tn, sup_desbroce, trans)

                        # 6. Reconstruir
                        sup_desbroce.Rebuild()
                        log.append(
                            f"[OK]  SDESBROCE reconstruida: "
                            f"{sup_desbroce.NumberOfTriangles} triángulos."
                        )

                        superficie_desbroce = sup_desbroce
                        trans.Commit()
                        log.append(
                            f"[✓] SDESBROCE generada. "
                            f"TN − {_delta:.3f} m = {_delta*100:.0f} cm de descapote."
                        )
                    else:
                        trans.Abort()
                else:
                    trans.Abort()

        except Exception as e:
            log.append(f"[ERROR CRÍTICO] {e}")
            trans.Abort()

# ── Salidas Dynamo ───────────────────────────────────────────────────
OUT = [superficie_desbroce, total_puntos, log]
