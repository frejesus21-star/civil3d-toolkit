"""
╔══════════════════════════════════════════════════════════════════════╗
║   RUN COMPLETO — Civil 3D Toolkit                                   ║
║   Ejecuta los 4 pasos en secuencia automática:                      ║
║     1. Alineamiento desde polilínea "EJE DE CAMINO"                 ║
║     2. Corredor vial con ensamble "camino"                          ║
║     3. Superficie de desbroce "SDESBROCE"                           ║
║     4. Vista de perfil longitudinal (TN · SDESBROCE · RASANTE)      ║
║   Compatible: Civil 3D 2018 → 2026                                  ║
╚══════════════════════════════════════════════════════════════════════╝

INPUTS (conectar nodos en Dynamo — todos tienen valor por defecto):
  IN[0] nombre_alineamiento  str   → ej: "EJE PRINCIPAL"   (def: "EJE PRINCIPAL")
  IN[1] nombre_rasante       str   → nombre del perfil rasante (def: "RASANTE")
  IN[2] capa_polilinea       str   → capa del eje dibujado  (def: "EJE DE CAMINO")
  IN[3] delta_desbroce       float → espesor descapote en m (def: 0.20)
  IN[4] pendiente_max        float → % máx. pendiente       (def: 12.0)
  IN[5] intervalo_corredor   float → intervalo de sección   (def: 5.0)
  IN[6] escala_h             float → escala horizontal vista (def: 1000.0)
  IN[7] escala_v             float → escala vertical vista   (def: 100.0)
  IN[8] sobrescribir         bool  → reconstruir si existe  (def: True)

OUTPUTS:
  OUT[0] resumen   → dict con ids de los objetos creados
  OUT[1] log       → lista completa de mensajes del proceso
"""

import clr
import sys
import math

# ── Carga de DLLs ────────────────────────────────────────────────────
for _ref in ['AeccDbMgd', 'AcMgd', 'AcCoreMgd', 'AcDbMgd']:
    try:
        clr.AddReference(_ref)
    except:
        pass

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    Transaction, OpenMode, ObjectId,
    Polyline, Polyline2d, Polyline3d,
    BlockTableRecord, BlockTable
)
from Autodesk.AutoCAD.Geometry import Point3d, Point2d

from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import (
    Alignment, AlignmentCreationOptions,
    Profile, ProfileView,
    Corridor,
    TinSurface,
)

doc      = Application.DocumentManager.MdiActiveDocument
db       = doc.Database
civil_db = CivilApplication.ActiveDocument
log      = []

# ════════════════════════════════════════════════════════════════════
# LECTURA DE INPUTS (con defaults si el nodo no está conectado)
# ════════════════════════════════════════════════════════════════════
def _in(idx, default, cast=str):
    try:
        v = IN[idx]
        if v is None or str(v).strip() == "":
            return default
        return cast(v)
    except:
        return default

_ali_nombre  = _in(0, "EJE PRINCIPAL", str).strip()
_ras_nombre  = _in(1, "RASANTE",       str).strip()
_capa        = _in(2, "EJE DE CAMINO", str).strip()
_delta       = _in(3, 0.20,            float)
_pend_max    = _in(4, 12.0,            float)
_intervalo   = _in(5, 5.0,             float)
_esc_h       = _in(6, 1000.0,          float)
_esc_v       = _in(7, 100.0,           float)
_sobrescribir= _in(8, True,            bool)

# Nombres fijos del proyecto
_TERRENO  = "TN"
_DESBROCE = "SDESBROCE"
_ENSAMBLE = "camino"

log.append("═" * 60)
log.append("  CIVIL 3D TOOLKIT — RUN COMPLETO")
log.append("═" * 60)
log.append(f"  Alineamiento : {_ali_nombre}")
log.append(f"  Rasante      : {_ras_nombre}")
log.append(f"  Capa eje     : {_capa}")
log.append(f"  Delta desc.  : {_delta} m")
log.append(f"  Pend. máx.   : {_pend_max} %")
log.append(f"  Intervalo    : {_intervalo} m")
log.append(f"  Escala H/V   : 1:{int(_esc_h)} / 1:{int(_esc_v)}")
log.append(f"  Sobrescribir : {_sobrescribir}")
log.append("═" * 60)


# ════════════════════════════════════════════════════════════════════
# HELPERS COMUNES
# ════════════════════════════════════════════════════════════════════
def get_surface(nombre, trans, modo=OpenMode.ForRead):
    for oid in civil_db.GetSurfaceIds():
        o = trans.GetObject(oid, modo)
        if hasattr(o, 'Name') and o.Name == nombre:
            return o
    return None

def get_alignment(nombre, trans, modo=OpenMode.ForRead):
    for oid in civil_db.GetAlignmentIds():
        o = trans.GetObject(oid, modo)
        if hasattr(o, 'Name') and o.Name == nombre:
            return o
    return None

def get_profile(ali, nombre, trans):
    try:
        for pid in ali.GetProfileIds():
            p = trans.GetObject(pid, OpenMode.ForRead)
            if hasattr(p, 'Name') and p.Name == nombre:
                return p
    except:
        pass
    return None

def get_assembly(nombre, trans):
    try:
        for oid in civil_db.GetAssemblyIds():
            o = trans.GetObject(oid, OpenMode.ForRead)
            if hasattr(o, 'Name') and o.Name == nombre:
                return o
    except:
        pass
    return None

def erase_if_exists_alignment(nombre, trans):
    try:
        for oid in civil_db.GetAlignmentIds():
            o = trans.GetObject(oid, OpenMode.ForRead)
            if hasattr(o, 'Name') and o.Name == nombre:
                if _sobrescribir:
                    trans.GetObject(oid, OpenMode.ForWrite).Erase()
                    log.append(f"  [INFO] Alineamiento '{nombre}' eliminado para recrear.")
                    return True
                else:
                    log.append(f"  [INFO] Alineamiento '{nombre}' ya existe. sobrescribir=False.")
                    return False
    except:
        pass
    return True

def erase_if_exists_surface(nombre, trans):
    try:
        for oid in civil_db.GetSurfaceIds():
            o = trans.GetObject(oid, OpenMode.ForRead)
            if hasattr(o, 'Name') and o.Name == nombre:
                if _sobrescribir:
                    trans.GetObject(oid, OpenMode.ForWrite).Erase()
                    log.append(f"  [INFO] Superficie '{nombre}' eliminada para recrear.")
                    return True
                else:
                    log.append(f"  [INFO] Superficie '{nombre}' ya existe. sobrescribir=False.")
                    return False
    except:
        pass
    return True


# ════════════════════════════════════════════════════════════════════
# PASO 1 — ALINEAMIENTO DESDE POLILÍNEA
# ════════════════════════════════════════════════════════════════════
def radio_desde_bulge(bulge, p1, p2):
    if abs(bulge) < 1e-9:
        return None
    cuerda = p1.GetDistanceTo(p2)
    if cuerda < 1e-9:
        return None
    angulo  = abs(4.0 * math.atan(bulge))
    divisor = 2.0 * math.sin(angulo / 2.0)
    if abs(divisor) < 1e-9:
        return None
    return cuerda / divisor

def analizar_pline(pline):
    segmentos = []
    n = pline.NumberOfVertices
    for i in range(n - 1):
        p1    = pline.GetPoint2dAt(i)
        p2    = pline.GetPoint2dAt(i + 1)
        bulge = pline.GetBulgeAt(i)
        radio = radio_desde_bulge(bulge, p1, p2)
        segmentos.append({
            'tipo': 'arco' if radio else 'tangente',
            'p1': p1, 'p2': p2,
            'bulge': bulge, 'radio': radio, 'cw': bulge < 0
        })
    if pline.Closed and n > 1:
        p1    = pline.GetPoint2dAt(n - 1)
        p2    = pline.GetPoint2dAt(0)
        bulge = pline.GetBulgeAt(n - 1)
        radio = radio_desde_bulge(bulge, p1, p2)
        segmentos.append({
            'tipo': 'arco' if radio else 'tangente',
            'p1': p1, 'p2': p2,
            'bulge': bulge, 'radio': radio, 'cw': bulge < 0
        })
    return segmentos

def buscar_plines(trans):
    capa_upper = _capa.upper()
    encontradas = []
    try:
        bt  = trans.GetObject(db.BlockTableId, OpenMode.ForRead)
        btr = trans.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead)
        for oid in btr:
            try:
                obj = trans.GetObject(oid, OpenMode.ForRead)
                if obj.Layer.upper() != capa_upper:
                    continue
                if isinstance(obj, Polyline):
                    encontradas.append(('LW', obj))
                elif isinstance(obj, Polyline2d):
                    encontradas.append(('2D', obj))
                elif isinstance(obj, Polyline3d):
                    log.append(
                        f"  [WARN] Polyline3D ignorada — no soporta arcos. "
                        "Usa Polyline para ejes con curvas."
                    )
            except:
                pass
    except Exception as e:
        log.append(f"  [ERROR] buscando polilíneas: {e}")
    return encontradas

def crear_alineamiento_manual(segmentos, estilo_ali, estilo_label, trans):
    try:
        ali_id = Alignment.Create(civil_db, _ali_nombre, None, estilo_ali, estilo_label)
        ali    = trans.GetObject(ali_id, OpenMode.ForWrite)
        ali.ReferencePointStation = 0.0
        ents   = ali.Entities
        n_t, n_a = 0, 0
        for seg in segmentos:
            if seg['tipo'] == 'tangente':
                try:
                    ents.AddFixedLine(seg['p1'], seg['p2'])
                    n_t += 1
                except Exception as e:
                    log.append(f"  [WARN] tangente: {e}")
            else:
                try:
                    ents.AddFixedCurve(seg['p1'], seg['p2'], seg['radio'], seg['cw'])
                    n_a += 1
                except Exception as e:
                    log.append(f"  [WARN] arco R={seg['radio']:.2f}m: {e} — agregado como tangente.")
                    try:
                        ents.AddFixedLine(seg['p1'], seg['p2'])
                        n_t += 1
                    except:
                        pass
        ali_r = trans.GetObject(ali_id, OpenMode.ForRead)
        log.append(f"  [OK]  Alineamiento manual: {n_t} tangentes + {n_a} arcos.")
        return ali_id, ali_r.Length
    except Exception as e:
        log.append(f"  [ERROR] alineamiento manual: {e}")
        return None, 0.0

def paso1_alineamiento(trans):
    log.append("")
    log.append("── PASO 1: ALINEAMIENTO ─────────────────────────────────")
    plines = buscar_plines(trans)
    if not plines:
        log.append(f"  [ERROR] Sin polilíneas en capa '{_capa}'. Verifica el nombre de capa.")
        return None, 0.0

    log.append(f"  [INFO] {len(plines)} polilínea(s) en '{_capa}'.")
    tipo_sel, pline_sel = max(plines, key=lambda x: x[1].Length)
    if len(plines) > 1:
        log.append(f"  [WARN] Se usa la más larga ({pline_sel.Length:.2f} m).")

    segmentos = analizar_pline(pline_sel) if tipo_sel == 'LW' else []
    n_t = sum(1 for s in segmentos if s['tipo'] == 'tangente')
    n_a = sum(1 for s in segmentos if s['tipo'] == 'arco')
    if segmentos:
        log.append(f"  [INFO] Geometría: {n_t} tangente(s) + {n_a} arco(s).")

    if not erase_if_exists_alignment(_ali_nombre, trans):
        ali = get_alignment(_ali_nombre, trans)
        return ali.ObjectId if ali else None, ali.Length if ali else 0.0

    estilo_ali   = civil_db.Styles.AlignmentStyles[0].ObjectId
    estilo_label = civil_db.Styles.LabelSetStyles.AlignmentLabelSetStyles[0].ObjectId

    try:
        try:
            opciones = AlignmentCreationOptions()
            opciones.StartingStation = 0.0
            ali_id = Alignment.Create(
                civil_db, pline_sel.ObjectId, _ali_nombre,
                None, estilo_ali, estilo_label, opciones
            )
        except:
            ali_id = Alignment.Create(
                civil_db, pline_sel.ObjectId, _ali_nombre,
                None, estilo_ali, estilo_label
            )

        ali = trans.GetObject(ali_id, OpenMode.ForRead)

        # Verificar si los arcos se transfirieron
        n_curvas = 0
        try:
            for i in range(ali.Entities.Count):
                t = type(ali.Entities[i]).__name__
                if 'Curve' in t or 'Arc' in t:
                    n_curvas += 1
        except:
            pass

        if n_a > 0 and n_curvas == 0 and segmentos:
            log.append(f"  [WARN] Create() no preservó los arcos. Usando método manual...")
            trans.GetObject(ali_id, OpenMode.ForWrite).Erase()
            return crear_alineamiento_manual(segmentos, estilo_ali, estilo_label, trans)

        log.append(f"  [OK]  Alineamiento '{_ali_nombre}' | L={ali.Length:.2f} m | {ali.Entities.Count} entidades.")
        return ali_id, ali.Length

    except Exception as e:
        log.append(f"  [WARN] Create() falló ({e}). Método manual...")
        return crear_alineamiento_manual(segmentos, estilo_ali, estilo_label, trans)


# ════════════════════════════════════════════════════════════════════
# PASO 2 — CORREDOR VIAL
# ════════════════════════════════════════════════════════════════════
def validar_pendientes(perfil):
    problemas = []
    try:
        pvis = perfil.PVIs
        for i in range(pvis.Count - 1):
            p1, p2 = pvis[i], pvis[i + 1]
            dist = abs(p2.Station - p1.Station)
            if dist > 0:
                pend = abs(p2.Elevation - p1.Elevation) / dist * 100
                if pend > _pend_max:
                    problemas.append({'desde': round(p1.Station, 2),
                                      'hasta': round(p2.Station, 2),
                                      'pendiente': round(pend, 2)})
                    log.append(f"  [ALERTA] Pendiente {pend:.2f}% entre Est. {p1.Station:.2f}–{p2.Station:.2f} m")
    except Exception as e:
        log.append(f"  [WARN] validando pendientes: {e}")
    return problemas

def paso2_corredor(trans):
    log.append("")
    log.append("── PASO 2: CORREDOR ─────────────────────────────────────")

    ali      = get_alignment(_ali_nombre, trans)
    terreno  = get_surface(_TERRENO,  trans)
    ensamble = get_assembly(_ENSAMBLE, trans)

    faltantes = []
    if not ali:      faltantes.append(f"Alineamiento '{_ali_nombre}'")
    if not terreno:  faltantes.append(f"Superficie '{_TERRENO}'")
    if not ensamble: faltantes.append(f"Ensamble '{_ENSAMBLE}'")
    if faltantes:
        log.append(f"  [ERROR] No encontrado: {' | '.join(faltantes)}")
        return None, []

    perfil = get_profile(ali, _ras_nombre, trans)
    if not perfil:
        log.append(f"  [ERROR] Perfil de rasante '{_ras_nombre}' no encontrado en '{_ali_nombre}'.")
        return None, []

    problemas = validar_pendientes(perfil)
    if not problemas:
        log.append(f"  [OK]  Pendientes dentro del criterio ({_pend_max}%).")

    nombre_corr = f"CORREDOR_{_ali_nombre}"

    # ¿Ya existe?
    try:
        for cid in civil_db.GetCorridorIds():
            c = trans.GetObject(cid, OpenMode.ForRead)
            if hasattr(c, 'Name') and c.Name == nombre_corr:
                if _sobrescribir:
                    cw = trans.GetObject(cid, OpenMode.ForWrite)
                    cw.Rebuild()
                    log.append(f"  [OK]  Corredor '{nombre_corr}' reconstruido.")
                    return cid, problemas
                else:
                    log.append(f"  [INFO] Corredor '{nombre_corr}' ya existe. sobrescribir=False.")
                    return cid, problemas
    except Exception as e:
        log.append(f"  [WARN] buscando corredor existente: {e}")

    # Crear
    try:
        corr_id = Corridor.Create(
            civil_db, nombre_corr,
            ali.ObjectId, perfil.ObjectId, ensamble.ObjectId
        )
        corr = trans.GetObject(corr_id, OpenMode.ForWrite)
        try:
            corr.Baselines[0].BaselineRegions[0].SamplingInterval = _intervalo
        except Exception as e:
            log.append(f"  [WARN] intervalo de muestreo: {e}")
        try:
            corr.AddSurface(terreno.ObjectId)
        except Exception as e:
            log.append(f"  [WARN] asociando superficie TN: {e}")
        corr.Rebuild()
        log.append(f"  [OK]  Corredor '{nombre_corr}' creado con ensamble '{_ENSAMBLE}'.")
        return corr_id, problemas
    except Exception as e:
        log.append(f"  [ERROR] creando corredor: {e}")
        return None, problemas


# ════════════════════════════════════════════════════════════════════
# PASO 3 — SUPERFICIE DESBROCE
# ════════════════════════════════════════════════════════════════════
def paso3_desbroce(trans):
    log.append("")
    log.append("── PASO 3: DESBROCE ─────────────────────────────────────")

    if _delta <= 0:
        log.append(f"  [ERROR] delta_desbroce debe ser > 0 (recibido: {_delta}).")
        return None, 0

    tn = get_surface(_TERRENO, trans)
    if not tn:
        log.append(f"  [ERROR] Superficie '{_TERRENO}' no encontrada.")
        return None, 0

    log.append(
        f"  [INFO] TN: {tn.Vertices.Count} vértices | "
        f"Z [{tn.FindMinimumElevation():.2f} – {tn.FindMaximumElevation():.2f}] m"
    )

    if not erase_if_exists_surface(_DESBROCE, trans):
        sup = get_surface(_DESBROCE, trans)
        return sup, sup.Vertices.Count if sup else 0

    # Crear superficie vacía
    sup_desb = None
    try:
        eid = civil_db.Styles.SurfaceStyles[0].ObjectId
        sid = TinSurface.Create(civil_db, _DESBROCE, eid)
        sup_desb = trans.GetObject(sid, OpenMode.ForWrite)
    except:
        try:
            sid = TinSurface.Create(civil_db, _DESBROCE)
            sup_desb = trans.GetObject(sid, OpenMode.ForWrite)
        except Exception as e:
            log.append(f"  [ERROR] creando superficie TIN: {e}")
            return None, 0

    sup_desb.Description = f"Desbroce TN − {_delta:.3f} m"

    # Copiar puntos con delta hacia abajo
    total = 0
    try:
        pts = [Point3d(v.Location.X, v.Location.Y, v.Location.Z - _delta)
               for v in tn.Vertices]
        BATCH = 500
        for i in range(0, len(pts), BATCH):
            for pt in pts[i:i + BATCH]:
                try:
                    sup_desb.AddPoint(pt)
                except:
                    pass
            total += len(pts[i:i + BATCH])
    except AttributeError:
        # Fallback por triángulos
        log.append("  [WARN] Usando triángulos como fuente de puntos...")
        vistos = set()
        try:
            for tri in tn.Triangles:
                for v in [tri.Vertex1, tri.Vertex2, tri.Vertex3]:
                    k = (round(v.Location.X, 4), round(v.Location.Y, 4))
                    if k not in vistos:
                        vistos.add(k)
                        try:
                            sup_desb.AddPoint(Point3d(
                                v.Location.X, v.Location.Y, v.Location.Z - _delta
                            ))
                            total += 1
                        except:
                            pass
        except Exception as e:
            log.append(f"  [ERROR] fallback triángulos: {e}")
    except Exception as e:
        log.append(f"  [ERROR] copiando puntos: {e}")

    sup_desb.Rebuild()
    log.append(
        f"  [OK]  SDESBROCE lista: {total} puntos | "
        f"{sup_desb.NumberOfTriangles} triángulos | "
        f"TN − {_delta*100:.0f} cm."
    )
    return sid, total


# ════════════════════════════════════════════════════════════════════
# PASO 4 — VISTA DE PERFIL LONGITUDINAL
# ════════════════════════════════════════════════════════════════════
def get_or_create_surface_profile(ali, sup, prefijo, trans):
    nombre = f"{prefijo}_{sup.Name}"
    try:
        for pid in ali.GetProfileIds():
            p = trans.GetObject(pid, OpenMode.ForRead)
            if hasattr(p, 'Name') and p.Name == nombre:
                log.append(f"  [INFO] Perfil '{nombre}' ya existe.")
                return p
    except:
        pass
    try:
        eid = civil_db.Styles.ProfileStyles[0].ObjectId
        lid = civil_db.Styles.LabelSetStyles.ProfileLabelSetStyles[0].ObjectId
        pid = Profile.CreateFromSurface(nombre, ali.ObjectId, sup.ObjectId, eid, lid)
        p   = trans.GetObject(pid, OpenMode.ForRead)
        log.append(f"  [OK]  Perfil '{nombre}' creado desde superficie '{sup.Name}'.")
        return p
    except Exception as e:
        log.append(f"  [ERROR] creando perfil desde '{sup.Name}': {e}")
        return None

def punto_insercion_derecha(ali):
    try:
        ext  = ali.GeomExtents
        off  = max(ali.Length * 0.10, 50.0)
        x    = ext.MaxPoint.X + off
        y    = (ext.MinPoint.Y + ext.MaxPoint.Y) / 2.0
        log.append(f"  [INFO] Vista insertada en X={x:.1f}, Y={y:.1f} (offset {off:.1f} m).")
        return Point3d(x, y, 0.0)
    except Exception as e:
        log.append(f"  [WARN] punto inserción: {e}. Usando origen.")
        return Point3d(0, 0, 0)

def paso4_vista_perfil(trans):
    log.append("")
    log.append("── PASO 4: VISTA DE PERFIL ──────────────────────────────")

    ali     = get_alignment(_ali_nombre, trans)
    sup_tn  = get_surface(_TERRENO,   trans)
    sup_dsb = get_surface(_DESBROCE,  trans)

    if not ali:
        log.append(f"  [ERROR] Alineamiento '{_ali_nombre}' no encontrado.")
        return None

    perf_tn  = get_or_create_surface_profile(ali, sup_tn,  "TN", trans) if sup_tn  else None
    perf_dsb = get_or_create_surface_profile(ali, sup_dsb, "SD", trans) if sup_dsb else None
    perf_ras = get_profile(ali, _ras_nombre, trans)

    if not perf_tn:  log.append(f"  [WARN] Sin perfil TN — superficie '{_TERRENO}' no disponible.")
    if not perf_dsb: log.append(f"  [WARN] Sin perfil desbroce — superficie '{_DESBROCE}' no disponible.")
    if not perf_ras: log.append(f"  [WARN] Sin perfil rasante '{_ras_nombre}' — agrégalo después.")

    nombre_vista = f"PL_{_ali_nombre}"

    # ¿Ya existe?
    try:
        for pvid in ali.GetProfileViewIds():
            pv = trans.GetObject(pvid, OpenMode.ForRead)
            if hasattr(pv, 'Name') and pv.Name == nombre_vista:
                log.append(f"  [INFO] Vista '{nombre_vista}' ya existe. Actualizando perfiles.")
                pv_w = trans.GetObject(pvid, OpenMode.ForWrite)
                for p in [perf_tn, perf_dsb, perf_ras]:
                    if p:
                        try: pv_w.AddProfile(p.ObjectId)
                        except: pass
                return pvid
    except Exception as e:
        log.append(f"  [WARN] buscando vista existente: {e}")

    pt_ins   = punto_insercion_derecha(ali)
    estilo_pv = civil_db.Styles.ProfileViewStyles[0].ObjectId

    try:
        try:
            from Autodesk.Civil.DatabaseServices import ProfileViewOptions
            opts = ProfileViewOptions()
            opts.DrawElevationGridlines = True
            pv_id = ProfileView.Create(
                civil_db, nombre_vista, ali.ObjectId, pt_ins, estilo_pv, opts
            )
        except:
            pv_id = ProfileView.Create(
                civil_db, nombre_vista, ali.ObjectId, pt_ins, estilo_pv
            )

        pv = trans.GetObject(pv_id, OpenMode.ForWrite)
        estilos_p = civil_db.Styles.ProfileStyles

        for i, perfil in enumerate([perf_tn, perf_dsb, perf_ras]):
            if perfil is None:
                continue
            try:
                eid = estilos_p[min(0 if i < 2 else 1, estilos_p.Count - 1)].ObjectId
                pv.AddProfile(perfil.ObjectId, eid)
                log.append(f"  [OK]  Perfil '{perfil.Name}' agregado a la vista.")
            except:
                try:
                    pv.AddProfile(perfil.ObjectId)
                    log.append(f"  [OK]  Perfil '{perfil.Name}' agregado (sin estilo).")
                except Exception as e:
                    log.append(f"  [WARN] no se pudo agregar '{perfil.Name}': {e}")

        log.append(f"  [OK]  Vista '{nombre_vista}' creada.")
        return pv_id

    except Exception as e:
        log.append(f"  [ERROR] creando vista de perfil: {e}")
        return None


# ════════════════════════════════════════════════════════════════════
# EJECUCIÓN COMPLETA EN SECUENCIA
# ════════════════════════════════════════════════════════════════════
resumen = {
    'alineamiento_id':  None,
    'corredor_id':      None,
    'desbroce_id':      None,
    'vista_perfil_id':  None,
    'pendientes_problema': [],
    'pasos_ok': []
}

with doc.LockDocument():
    # ── Paso 1: Alineamiento ──────────────────────────────────────
    with db.TransactionManager.StartTransaction() as trans:
        try:
            ali_id, ali_long = paso1_alineamiento(trans)
            if ali_id:
                trans.Commit()
                resumen['alineamiento_id'] = ali_id
                resumen['pasos_ok'].append('ALINEAMIENTO')
                log.append(f"  [✓] Paso 1 completado. L = {ali_long:.2f} m")
            else:
                trans.Abort()
                log.append("  [✗] Paso 1 FALLIDO — los pasos siguientes pueden fallar.")
        except Exception as e:
            log.append(f"  [ERROR CRÍTICO] Paso 1: {e}")
            trans.Abort()

    # ── Paso 2: Corredor ─────────────────────────────────────────
    with db.TransactionManager.StartTransaction() as trans:
        try:
            corr_id, problemas = paso2_corredor(trans)
            if corr_id:
                trans.Commit()
                resumen['corredor_id']        = corr_id
                resumen['pendientes_problema'] = problemas
                resumen['pasos_ok'].append('CORREDOR')
                log.append(f"  [✓] Paso 2 completado. Tramos con pend > {_pend_max}%: {len(problemas)}")
            else:
                trans.Abort()
                log.append("  [✗] Paso 2 FALLIDO.")
        except Exception as e:
            log.append(f"  [ERROR CRÍTICO] Paso 2: {e}")
            trans.Abort()

    # ── Paso 3: Desbroce ─────────────────────────────────────────
    with db.TransactionManager.StartTransaction() as trans:
        try:
            dsb_id, n_pts = paso3_desbroce(trans)
            if dsb_id:
                trans.Commit()
                resumen['desbroce_id'] = dsb_id
                resumen['pasos_ok'].append('DESBROCE')
                log.append(f"  [✓] Paso 3 completado. {n_pts} puntos procesados.")
            else:
                trans.Abort()
                log.append("  [✗] Paso 3 FALLIDO.")
        except Exception as e:
            log.append(f"  [ERROR CRÍTICO] Paso 3: {e}")
            trans.Abort()

    # ── Paso 4: Vista de Perfil ──────────────────────────────────
    with db.TransactionManager.StartTransaction() as trans:
        try:
            pv_id = paso4_vista_perfil(trans)
            if pv_id:
                trans.Commit()
                resumen['vista_perfil_id'] = pv_id
                resumen['pasos_ok'].append('VISTA PERFIL')
                log.append(f"  [✓] Paso 4 completado.")
            else:
                trans.Abort()
                log.append("  [✗] Paso 4 FALLIDO.")
        except Exception as e:
            log.append(f"  [ERROR CRÍTICO] Paso 4: {e}")
            trans.Abort()

# ── Resumen final ────────────────────────────────────────────────
log.append("")
log.append("═" * 60)
n_ok = len(resumen['pasos_ok'])
log.append(f"  RESULTADO: {n_ok}/4 pasos completados")
if resumen['pasos_ok']:
    log.append(f"  OK  → {' · '.join(resumen['pasos_ok'])}")
pasos_fallidos = [p for p in ['ALINEAMIENTO','CORREDOR','DESBROCE','VISTA PERFIL']
                  if p not in resumen['pasos_ok']]
if pasos_fallidos:
    log.append(f"  FAIL→ {' · '.join(pasos_fallidos)}")
log.append("═" * 60)

OUT = [resumen, log]
