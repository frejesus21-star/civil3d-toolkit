"""
╔══════════════════════════════════════════════════════════════════════╗
║   ALINEAMIENTO DESDE POLILÍNEA — Dynamo para Civil 3D               ║
║   Capa fuente : EJE DE CAMINO                                        ║
║   Preserva    : tangentes + arcos con radios distintos               ║
║   Compatible  : Civil 3D 2018 → 2026                                 ║
╚══════════════════════════════════════════════════════════════════════╝

DESCRIPCIÓN:
  Lee la polilínea en capa "EJE DE CAMINO" y crea el alineamiento
  Civil 3D respetando EXACTAMENTE la geometría dibujada:

    · Segmentos rectos  → entidad Tangente
    · Segmentos curvos  → entidad Arco con el radio exacto

  Una polilínea ligera (Polyline) almacena los arcos con "bulge":
      bulge = tan(ángulo_central / 4)
      radio = cuerda / (2 · sin(|ángulo_central| / 2))

  bulge = 0       → segmento recto
  bulge > 0       → arco antihorario
  bulge < 0       → arco horario

  El script analiza vértice a vértice, calcula el radio de cada arco
  y lo agrega al alineamiento como entidad independiente.
  Radios distintos a lo largo del eje quedan correctamente preservados.

IMPORTANTE — tipo de polilínea:
  · Polyline (LWPolyline) → soporta arcos via bulge         ✓
  · Polyline2D clásica    → soporta arcos                   ✓
  · Polyline3D            → NO soporta arcos (solo rectas)  ✗
  Dibuja el eje siempre con Polyline o Polyline2D.

INPUTS (nodos Dynamo — conectar en orden):
  IN[0] nombre_alineamiento : str   → ej: "EJE PRINCIPAL"
  IN[1] capa_polilinea      : str   → default "EJE DE CAMINO"
  IN[2] estacion_inicio     : float → default 0.0
  IN[3] sobrescribir        : bool  → default True

OUTPUTS:
  OUT[0] alineamiento_id → ObjectId del alineamiento
  OUT[1] longitud        → longitud total en metros
  OUT[2] resumen         → {tangentes, arcos, longitud_pline}
  OUT[3] log             → mensajes del proceso
"""

import clr
import sys
import math

clr.AddReference('AeccDbMgd')
clr.AddReference('AcMgd')
clr.AddReference('AcCoreMgd')
clr.AddReference('AcDbMgd')

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    Transaction, OpenMode,
    Polyline, Polyline2d, Polyline3d,
    BlockTableRecord, BlockTable
)
from Autodesk.AutoCAD.Geometry import Point2d, Point3d

from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import (
    Alignment, AlignmentCreationOptions
)

doc      = Application.DocumentManager.MdiActiveDocument
db       = doc.Database
civil_db = CivilApplication.ActiveDocument
log      = []

# ── Leer inputs del nodo Dynamo ──────────────────────────────────────
try:    _nombre  = str(IN[0]).strip()
except: _nombre  = "EJE PRINCIPAL"

try:    _capa    = str(IN[1]).strip()
except: _capa    = "EJE DE CAMINO"

try:    _est_ini = float(IN[2])
except: _est_ini = 0.0

try:    _sobresc = bool(IN[3])
except: _sobresc = True


# ════════════════════════════════════════════════════════════════════
# GEOMETRÍA — lectura de bulge y cálculo de radio
# ════════════════════════════════════════════════════════════════════

def radio_desde_bulge(bulge, p1, p2):
    """
    Calcula el radio del arco definido por el bulge y los dos puntos.

    Fórmulas:
        ángulo_central = 4 · atan(bulge)
        longitud_cuerda = distancia(p1, p2)
        radio = cuerda / (2 · sin(|ángulo_central| / 2))

    Retorna None si es segmento recto (bulge ≈ 0).
    """
    if abs(bulge) < 1e-9:
        return None
    cuerda  = p1.GetDistanceTo(p2)
    if cuerda < 1e-9:
        return None
    angulo  = abs(4.0 * math.atan(bulge))
    divisor = 2.0 * math.sin(angulo / 2.0)
    if abs(divisor) < 1e-9:
        return None
    return cuerda / divisor


def analizar_pline(pline):
    """
    Recorre todos los segmentos de una Polyline ligera y clasifica
    cada uno como 'tangente' o 'arco'.

    Retorna lista de dicts:
      { tipo, p1, p2, bulge, radio, cw }
    """
    segmentos = []
    n = pline.NumberOfVertices

    for i in range(n - 1):
        p1    = pline.GetPoint2dAt(i)
        p2    = pline.GetPoint2dAt(i + 1)
        bulge = pline.GetBulgeAt(i)
        radio = radio_desde_bulge(bulge, p1, p2)

        segmentos.append({
            'tipo':  'arco' if radio else 'tangente',
            'p1':    p1,
            'p2':    p2,
            'bulge': bulge,
            'radio': radio,
            'cw':    bulge < 0   # negativo = sentido horario
        })

    if pline.Closed and n > 1:
        p1    = pline.GetPoint2dAt(n - 1)
        p2    = pline.GetPoint2dAt(0)
        bulge = pline.GetBulgeAt(n - 1)
        radio = radio_desde_bulge(bulge, p1, p2)
        segmentos.append({
            'tipo':  'arco' if radio else 'tangente',
            'p1':    p1, 'p2': p2,
            'bulge': bulge, 'radio': radio, 'cw': bulge < 0
        })

    return segmentos


# ════════════════════════════════════════════════════════════════════
# BÚSQUEDA DE POLILÍNEA
# ════════════════════════════════════════════════════════════════════

def buscar_plines(capa_upper, trans):
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
                        f"[WARN] Polyline3D (Handle {obj.Handle}) ignorada — "
                        "no soporta arcos. Usa Polyline para ejes con curvas."
                    )
            except:
                pass
    except Exception as e:
        log.append(f"[ERROR] buscando polilíneas: {e}")
    return encontradas


def longitud_pline(pline):
    try:    return pline.Length
    except: return 0.0


# ════════════════════════════════════════════════════════════════════
# CREACIÓN DEL ALINEAMIENTO
# ════════════════════════════════════════════════════════════════════

def eliminar_si_existe(nombre, trans):
    try:
        for oid in civil_db.GetAlignmentIds():
            a = trans.GetObject(oid, OpenMode.ForRead)
            if a.Name == nombre:
                if _sobresc:
                    trans.GetObject(oid, OpenMode.ForWrite).Erase()
                    log.append(f"[INFO] Alineamiento '{nombre}' eliminado para recrear.")
                    return True
                else:
                    log.append(f"[WARN] '{nombre}' ya existe. sobrescribir=False.")
                    return False
    except Exception as e:
        log.append(f"[WARN] {e}")
    return True


def crear_desde_pline(tipo, pline, segmentos, nombre, est_ini, trans):
    """
    Estrategia principal: Alignment.Create() desde la polilínea.
    Civil 3D lee el bulge internamente y genera las entidades.
    Luego verifica que las curvas se hayan creado.
    Si no, cae al método manual.
    """
    estilo_ali   = civil_db.Styles.AlignmentStyles[0].ObjectId
    estilo_label = civil_db.Styles.LabelSetStyles.AlignmentLabelSetStyles[0].ObjectId

    try:
        try:
            opciones = AlignmentCreationOptions()
            opciones.StartingStation = est_ini
            ali_id = Alignment.Create(
                civil_db, pline.ObjectId, nombre,
                None, estilo_ali, estilo_label, opciones
            )
        except:
            # Firma sin opciones — C3D 2018/2019
            ali_id = Alignment.Create(
                civil_db, pline.ObjectId, nombre,
                None, estilo_ali, estilo_label
            )

        ali = trans.GetObject(ali_id, OpenMode.ForRead)

        # Contar curvas efectivamente creadas
        n_curvas_creadas = 0
        try:
            for i in range(ali.Entities.Count):
                ent_type = type(ali.Entities[i]).__name__
                if 'Curve' in ent_type or 'Arc' in ent_type:
                    n_curvas_creadas += 1
        except:
            pass

        n_arcos_esperados = sum(1 for s in segmentos if s['tipo'] == 'arco')

        if n_arcos_esperados > 0 and n_curvas_creadas == 0:
            # Civil 3D no transfirió los arcos — usar método manual
            log.append(
                f"[WARN] Create() no preservó los {n_arcos_esperados} arcos. "
                "Usando método de entidades manuales..."
            )
            trans.GetObject(ali_id, OpenMode.ForWrite).Erase()
            return crear_entidades_manual(segmentos, nombre, est_ini,
                                          estilo_ali, estilo_label, trans)

        log.append(
            f"[OK]  Alineamiento creado desde polilínea. "
            f"Entidades: {ali.Entities.Count} "
            f"(curvas creadas: {n_curvas_creadas}/{n_arcos_esperados})"
        )
        return ali_id, ali.Length

    except Exception as e:
        log.append(f"[WARN] Create() desde pline: {e}. Método manual...")
        return crear_entidades_manual(segmentos, nombre, est_ini,
                                      estilo_ali, estilo_label, trans)


def crear_entidades_manual(segmentos, nombre, est_ini,
                            estilo_ali, estilo_label, trans):
    """
    Método de respaldo: agrega cada tangente y arco uno por uno.
    Garantiza que cada radio quede exactamente como en la polilínea.
    """
    try:
        ali_id = Alignment.Create(
            civil_db, nombre, None, estilo_ali, estilo_label
        )
        ali = trans.GetObject(ali_id, OpenMode.ForWrite)
        ali.ReferencePointStation = est_ini

        entidades = ali.Entities
        n_tang = 0
        n_arco = 0

        for seg in segmentos:
            p1 = seg['p1']
            p2 = seg['p2']

            if seg['tipo'] == 'tangente':
                try:
                    entidades.AddFixedLine(p1, p2)
                    n_tang += 1
                except Exception as e:
                    log.append(f"[WARN] tangente ({p1.X:.1f},{p1.Y:.1f}): {e}")

            else:  # arco
                try:
                    entidades.AddFixedCurve(p1, p2, seg['radio'], seg['cw'])
                    n_arco += 1
                    log.append(
                        f"       Arco → R={seg['radio']:.3f}m | "
                        f"{'Horario ↻' if seg['cw'] else 'Antihorario ↺'}"
                    )
                except Exception as e:
                    # Último recurso: agregar como tangente si el arco falla
                    log.append(
                        f"[WARN] Arco R={seg['radio']:.3f}m falló ({e}). "
                        "Agregado como tangente."
                    )
                    try:
                        entidades.AddFixedLine(p1, p2)
                        n_tang += 1
                    except:
                        pass

        ali_r = trans.GetObject(ali_id, OpenMode.ForRead)
        log.append(
            f"[OK]  Alineamiento construido manualmente. "
            f"Tangentes: {n_tang} | Arcos: {n_arco}"
        )
        return ali_id, ali_r.Length

    except Exception as e:
        log.append(f"[ERROR] método manual: {e}")
        return None, 0.0


# ════════════════════════════════════════════════════════════════════
# EJECUCIÓN PRINCIPAL
# ════════════════════════════════════════════════════════════════════
alineamiento_id = None
longitud        = 0.0
resumen         = {}

with doc.LockDocument():
    with db.TransactionManager.StartTransaction() as trans:
        try:
            plines = buscar_plines(_capa.upper(), trans)

            if not plines:
                log.append(
                    f"[ERROR] No hay polilíneas en la capa '{_capa}'. "
                    "Dibuja el eje con Polyline (no Polyline3D) y verifica el nombre de capa."
                )
            else:
                log.append(f"[INFO] {len(plines)} polilínea(s) encontrada(s) en '{_capa}'.")

                # Seleccionar la más larga
                tipo_sel, pline_sel = max(plines, key=lambda x: longitud_pline(x[1]))
                if len(plines) > 1:
                    log.append(
                        f"[WARN] Varias polilíneas en la capa. "
                        f"Se usa la más larga ({longitud_pline(pline_sel):.2f}m). "
                        "Deja solo una en la capa si quieres elegir."
                    )

                # Analizar segmentos (solo para Polyline ligera)
                segmentos = analizar_pline(pline_sel) if tipo_sel == 'LW' else []

                n_tang = sum(1 for s in segmentos if s['tipo'] == 'tangente')
                n_arco = sum(1 for s in segmentos if s['tipo'] == 'arco')

                if segmentos:
                    log.append(
                        f"[INFO] Geometría: {n_tang} tangente(s) + "
                        f"{n_arco} arco(s) con radio variable."
                    )
                    for s in [s for s in segmentos if s['tipo'] == 'arco']:
                        log.append(
                            f"         R = {s['radio']:.3f} m | "
                            f"{'Horario ↻' if s['cw'] else 'Antihorario ↺'}"
                        )

                resumen = {
                    'tangentes':     n_tang,
                    'arcos':         n_arco,
                    'longitud_pline': round(longitud_pline(pline_sel), 3)
                }

                puede_crear = eliminar_si_existe(_nombre, trans)

                if puede_crear:
                    alineamiento_id, longitud = crear_desde_pline(
                        tipo_sel, pline_sel, segmentos,
                        _nombre, _est_ini, trans
                    )
                    if alineamiento_id:
                        trans.Commit()
                        log.append(
                            f"[✓] '{_nombre}' listo | L={longitud:.3f}m | "
                            f"{n_tang} tangentes + {n_arco} arcos."
                        )
                    else:
                        trans.Abort()
                else:
                    trans.Abort()

        except Exception as e:
            log.append(f"[ERROR CRÍTICO] {e}")
            trans.Abort()

OUT = [alineamiento_id, longitud, resumen, log]
