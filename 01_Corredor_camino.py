"""
╔══════════════════════════════════════════════════════════════════════╗
║   CORREDOR VIAL — Dynamo para Civil 3D                              ║
║   Subensamble: "camino" | Compatible: 2018 → 2026                   ║
╚══════════════════════════════════════════════════════════════════════╝

DESCRIPCIÓN:
  Crea o actualiza el corredor vial usando:
    · Alineamiento generado desde polilínea "EJE DE CAMINO"
    · Perfil de rasante existente en el alineamiento
    · Ensamble/subensamble llamado "camino"
    · Superficie de terreno "TN"

  Valida pendientes antes de construir y reporta tramos que
  superen la pendiente máxima configurada.

INPUTS (nodos Dynamo):
  - nombre_alineamiento   : str   → nombre del alineamiento (ej: "EJE PRINCIPAL")
  - nombre_rasante        : str   → nombre del perfil de rasante
  - pendiente_max         : float → pendiente máxima permitida en %
  - intervalo_muestreo    : float → intervalo de sección del corredor en metros
  - sobrescribir          : bool  → True = reconstruye si el corredor ya existe

OUTPUTS:
  - corredor_id         → ObjectId del corredor creado
  - estaciones_problema → lista de tramos fuera de pendiente
  - log                 → mensajes del proceso

NOMBRES FIJOS (no requieren input):
  - Superficie terreno : "TN"
  - Subensamble        : "camino"
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
from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import (
    Alignment, Profile, Corridor, TinSurface
)

doc      = Application.DocumentManager.MdiActiveDocument
db       = doc.Database
civil_db = CivilApplication.ActiveDocument
log      = []

# ── Nombres fijos del proyecto ───────────────────────────────────────
NOMBRE_TERRENO    = "TN"
NOMBRE_ENSAMBLE   = "camino"

# ── Defaults de inputs ───────────────────────────────────────────────
try:    _ali_nombre   = str(nombre_alineamiento).strip()
except: _ali_nombre   = "EJE PRINCIPAL"

try:    _ras_nombre   = str(nombre_rasante).strip()
except: _ras_nombre   = "RASANTE"

try:    _pend_max     = float(pendiente_max)
except: _pend_max     = 12.0

try:    _intervalo    = float(intervalo_muestreo)
except: _intervalo    = 5.0

try:    _sobrescribir = bool(sobrescribir)
except: _sobrescribir = True


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


def get_assembly(nombre, trans, modo=OpenMode.ForRead):
    """
    Busca el ensamble por nombre.
    GetAssemblyIds() disponible en todas las versiones.
    """
    try:
        for oid in civil_db.GetAssemblyIds():
            o = trans.GetObject(oid, modo)
            if hasattr(o, 'Name') and o.Name == nombre:
                return o
    except Exception as e:
        log.append(f"[WARN] buscando ensamble '{nombre}': {e}")
    return None


def get_profile(ali, nombre, trans):
    """Busca perfil por nombre dentro de un alineamiento."""
    try:
        for pid in ali.GetProfileIds():
            p = trans.GetObject(pid, OpenMode.ForRead)
            if hasattr(p, 'Name') and p.Name == nombre:
                return p
    except Exception as e:
        log.append(f"[WARN] buscando perfil '{nombre}': {e}")
    return None


def validar_pendientes(perfil, pend_max):
    """
    Recorre PVIs del perfil y detecta tramos con pendiente > pend_max.
    Retorna lista de dicts con la info de cada tramo problemático.
    """
    problemas = []
    try:
        pvis = perfil.PVIs
        for i in range(pvis.Count - 1):
            p1 = pvis[i]
            p2 = pvis[i + 1]
            dist = abs(p2.Station - p1.Station)
            if dist > 0:
                pend = abs(p2.Elevation - p1.Elevation) / dist * 100
                if pend > pend_max:
                    problemas.append({
                        'desde': round(p1.Station, 2),
                        'hasta': round(p2.Station, 2),
                        'pendiente': round(pend, 2)
                    })
                    log.append(
                        f"[ALERTA] Pendiente {pend:.2f}% entre "
                        f"Est. {p1.Station:.2f} – {p2.Station:.2f} m "
                        f"(máx. permitida: {pend_max}%)"
                    )
    except Exception as e:
        log.append(f"[WARN] validando pendientes: {e}")
    return problemas


def crear_o_reconstruir_corredor(ali, perfil, ensamble, terreno, intervalo, trans):
    """
    Crea el corredor si no existe, o lo reconstruye si _sobrescribir=True.
    Nombre del corredor = "CORREDOR_" + nombre del alineamiento.
    """
    nombre_corr = f"CORREDOR_{ali.Name}"

    # ¿Ya existe?
    try:
        for cid in civil_db.GetCorridorIds():
            c = trans.GetObject(cid, OpenMode.ForRead)
            if hasattr(c, 'Name') and c.Name == nombre_corr:
                if _sobrescribir:
                    cw = trans.GetObject(cid, OpenMode.ForWrite)
                    cw.Rebuild()
                    log.append(f"[OK]  Corredor '{nombre_corr}' reconstruido.")
                    return cid
                else:
                    log.append(f"[INFO] Corredor '{nombre_corr}' ya existe. sobrescribir=False.")
                    return cid
    except Exception as e:
        log.append(f"[WARN] buscando corredor existente: {e}")

    # Crear nuevo
    try:
        corr_id = Corridor.Create(
            civil_db,
            nombre_corr,
            ali.ObjectId,
            perfil.ObjectId,
            ensamble.ObjectId
        )
        corr = trans.GetObject(corr_id, OpenMode.ForWrite)

        # Intervalo de muestreo en la región
        try:
            baseline = corr.Baselines[0]
            region   = baseline.BaselineRegions[0]
            region.SamplingInterval = intervalo
            log.append(f"[INFO] Intervalo de muestreo: {intervalo} m.")
        except Exception as e:
            log.append(f"[WARN] asignando intervalo: {e}")

        # Asociar superficie TN
        try:
            corr.AddSurface(terreno.ObjectId)
            log.append(f"[INFO] Superficie '{terreno.Name}' asociada al corredor.")
        except Exception as e:
            log.append(f"[WARN] asociando superficie: {e}")

        corr.Rebuild()
        log.append(
            f"[OK]  Corredor '{nombre_corr}' creado con ensamble '{NOMBRE_ENSAMBLE}'. "
            f"Reconstruido correctamente."
        )
        return corr_id

    except Exception as e:
        log.append(f"[ERROR] creando corredor: {e}")
        return None


# ── EJECUCIÓN PRINCIPAL ──────────────────────────────────────────────
corredor_id          = None
estaciones_problema  = []

with doc.LockDocument():
    with db.TransactionManager.StartTransaction() as trans:
        try:
            ali      = get_alignment(_ali_nombre,  trans)
            terreno  = get_surface(NOMBRE_TERRENO,  trans)
            ensamble = get_assembly(NOMBRE_ENSAMBLE, trans)

            # Validaciones
            faltantes = []
            if not ali:      faltantes.append(f"Alineamiento '{_ali_nombre}'")
            if not terreno:  faltantes.append(f"Superficie '{NOMBRE_TERRENO}'")
            if not ensamble: faltantes.append(f"Ensamble '{NOMBRE_ENSAMBLE}'")

            if faltantes:
                log.append(f"[ERROR] No encontrado(s): {' | '.join(faltantes)}")
            else:
                # Buscar perfil de rasante
                perfil = get_profile(ali, _ras_nombre, trans)
                if not perfil:
                    log.append(
                        f"[ERROR] Perfil '{_ras_nombre}' no encontrado en "
                        f"el alineamiento '{_ali_nombre}'."
                    )
                else:
                    log.append(
                        f"[INFO] Usando → Ali: '{ali.Name}' | "
                        f"Rasante: '{perfil.Name}' | "
                        f"Ensamble: '{ensamble.Name}' | "
                        f"Terreno: '{terreno.Name}'"
                    )

                    # Validar pendientes antes de construir
                    estaciones_problema = validar_pendientes(perfil, _pend_max)
                    if not estaciones_problema:
                        log.append("[OK]  Pendientes dentro del criterio máximo.")

                    # Crear/reconstruir corredor
                    corredor_id = crear_o_reconstruir_corredor(
                        ali, perfil, ensamble, terreno, _intervalo, trans
                    )

                    if corredor_id:
                        trans.Commit()
                        log.append(
                            f"[✓] Corredor listo. "
                            f"Tramos con pendiente > {_pend_max}%: {len(estaciones_problema)}"
                        )
                    else:
                        trans.Abort()

        except Exception as e:
            log.append(f"[ERROR CRÍTICO] {e}")
            trans.Abort()

OUT = [corredor_id, estaciones_problema, log]
