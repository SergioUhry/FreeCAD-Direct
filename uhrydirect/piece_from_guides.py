# -*- coding: utf-8 -*-
"""
Peça pelas Guias 0.2 — integrada à Direct

Fluxo:
1) Selecione exatamente 4 Linhas Guia coplanares.
2) A macro identifica 2 pares de guias paralelas.
3) Calcula os 4 cruzamentos matemáticos.
4) Cria um novo PartDesign::Body.
5) Cria um Sketch fechado passando pelos 4 cruzamentos.
6) Abre o Pad nativo do Part Design para digitar a extrusão.

A ferramenta NÃO depende de snap visual e NÃO cria links externos entre
Body/Sketch e as Linhas Guia. Os pontos são calculados no momento da criação,
evita problemas de escopo do PartDesign.
"""

import math
import traceback

import FreeCAD as App
import FreeCADGui as Gui
import Part
import Sketcher

try:
    from PySide import QtWidgets
except ImportError:
    try:
        from PySide2 import QtWidgets
    except ImportError:
        from PySide6 import QtWidgets


VERSION = "0.2"
GUIDE_FLAG = "UhryGuiaReferencia"
DIRECT_GUIDE_FLAG = "DirectGuiaReferencia"
TOL = 1e-7
PARALLEL_TOL = 1e-4
PLANE_TOL_MM = 0.20
INTERSECTION_TOL_MM = 0.20


def unit(v):
    out = App.Vector(v)
    if out.Length < TOL:
        raise ValueError("Vetor de comprimento zero.")
    out.normalize()
    return out


def is_guide(obj):
    if obj is None:
        return False
    props = getattr(obj, "PropertiesList", [])
    return (
        (GUIDE_FLAG in props and bool(getattr(obj, GUIDE_FLAG, False)))
        or (DIRECT_GUIDE_FLAG in props and bool(getattr(obj, DIRECT_GUIDE_FLAG, False)))
    )


def selected_guides():
    """Retorna as Linhas Guia selecionadas, sem repetir o mesmo objeto."""
    try:
        sels = Gui.Selection.getSelectionEx("", 0)
    except Exception:
        sels = Gui.Selection.getSelectionEx()

    result = []
    seen = set()

    for sel in sels:
        obj = sel.Object
        if not is_guide(obj):
            continue
        key = (getattr(obj, "Document", None), obj.Name)
        if key not in seen:
            seen.add(key)
            result.append(obj)

    return result


def global_shape(obj):
    """Obtém a Shape exatamente na posição GLOBAL mostrada pelo FreeCAD.

    IMPORTANTE:
    Não aplicar getGlobalPlacement() manualmente sobre obj.Shape. Em objetos
    Part::Feature/Linha Guia isso pode aplicar o Placement duas vezes.
    Part.getShape(..., transform=True) já resolve o Placement do objeto e de
    contêineres, retornando a geometria na posição visual real.
    """
    try:
        shape = Part.getShape(
            obj,
            "",
            needSubElement=False,
            transform=True,
        )
        if shape is not None and not shape.isNull():
            return shape
    except Exception:
        pass

    if not hasattr(obj, "Shape") or obj.Shape is None or obj.Shape.isNull():
        raise ValueError(f"{obj.Label}: guia sem geometria válida.")

    # Fallback: obj.Shape.copy() sem reaplicar Placement.
    return obj.Shape.copy()


def guide_line(obj):
    """Retorna ponto-base e direção unitária de uma Linha Guia em global."""
    shape = global_shape(obj)

    if getattr(shape, "ShapeType", "") == "Edge":
        edge = shape
    elif getattr(shape, "Edges", None):
        if len(shape.Edges) != 1:
            raise ValueError(f"{obj.Label}: a guia não possui uma única aresta.")
        edge = shape.Edges[0]
    else:
        raise ValueError(f"{obj.Label}: guia sem aresta válida.")

    verts = edge.Vertexes
    if len(verts) < 2:
        raise ValueError(f"{obj.Label}: a aresta não possui dois extremos.")

    p1 = App.Vector(verts[0].Point)
    p2 = App.Vector(verts[-1].Point)
    d = unit(p2 - p1)
    mid = (p1 + p2) * 0.5

    return {
        "obj": obj,
        "p": mid,
        "d": d,
        "p1": p1,
        "p2": p2,
    }


def are_parallel(a, b):
    return abs(abs(a.dot(b)) - 1.0) <= PARALLEL_TOL


def classify_pairs(lines):
    """Encontra a combinação 2+2 em que cada par é paralelo."""
    pairings = [
        ((0, 1), (2, 3)),
        ((0, 2), (1, 3)),
        ((0, 3), (1, 2)),
    ]

    for pair_a, pair_b in pairings:
        a0, a1 = lines[pair_a[0]], lines[pair_a[1]]
        b0, b1 = lines[pair_b[0]], lines[pair_b[1]]

        if not are_parallel(a0["d"], a1["d"]):
            continue
        if not are_parallel(b0["d"], b1["d"]):
            continue
        if are_parallel(a0["d"], b0["d"]):
            continue

        return [a0, a1], [b0, b1]

    raise ValueError(
        "As 4 guias precisam formar 2 pares de linhas paralelas.\n"
        "Exemplo: esquerda/direita + superior/inferior."
    )


def line_distance_if_parallel(line_a, line_b):
    """Distância mínima entre duas retas paralelas."""
    d = line_a["d"]
    delta = line_b["p"] - line_a["p"]
    perpendicular = delta - d * delta.dot(d)
    return perpendicular.Length


def validate_families(family_a, family_b):
    if line_distance_if_parallel(family_a[0], family_a[1]) < PLANE_TOL_MM:
        raise ValueError("As duas guias do primeiro par estão sobre a mesma reta.")
    if line_distance_if_parallel(family_b[0], family_b[1]) < PLANE_TOL_MM:
        raise ValueError("As duas guias do segundo par estão sobre a mesma reta.")

    u = unit(family_a[0]["d"])
    v = unit(family_b[0]["d"])
    n = u.cross(v)
    if n.Length < TOL:
        raise ValueError("Os dois pares de guias ficaram paralelos entre si.")
    n.normalize()

    origin = family_a[0]["p"]
    for line in family_a + family_b:
        dist = abs((line["p"] - origin).dot(n))
        if dist > PLANE_TOL_MM:
            raise ValueError(
                "As quatro guias não estão no mesmo plano.\n"
                f"Desvio encontrado: {dist:.3f} mm."
            )

    return n


def intersect_lines(line_a, line_b):
    """Interseção 3D entre duas retas coplanares e não paralelas."""
    p = line_a["p"]
    q = line_b["p"]
    u = unit(line_a["d"])
    v = unit(line_b["d"])

    w0 = p - q
    a = u.dot(u)
    b = u.dot(v)
    c = v.dot(v)
    d = u.dot(w0)
    e = v.dot(w0)
    denom = a * c - b * b

    if abs(denom) < TOL:
        raise ValueError("Não foi possível calcular o cruzamento: linhas paralelas.")

    t = (b * e - c * d) / denom
    s = (a * e - b * d) / denom

    pa = p + u * t
    pb = q + v * s
    gap = (pa - pb).Length

    if gap > INTERSECTION_TOL_MM:
        raise ValueError(
            "Duas guias não se cruzam no mesmo plano.\n"
            f"Diferença no cruzamento: {gap:.3f} mm."
        )

    return (pa + pb) * 0.5


def camera_axes():
    """Eixos direita/cima/direção da câmera em coordenadas globais."""
    view = Gui.activeDocument().activeView()
    rot = view.getCameraOrientation()

    def mv(v):
        try:
            return rot.multVec(v)
        except Exception:
            return App.Rotation(rot).multVec(v)

    right = unit(mv(App.Vector(1, 0, 0)))
    up = unit(mv(App.Vector(0, 1, 0)))
    view_dir = unit(mv(App.Vector(0, 0, -1)))
    return right, up, view_dir


def visual_frame(normal, corners):
    """
    Monta o frame do Body/Sketch preservando a leitura visual:
    direita da tela = +X e cima da tela = +Y.
    """
    right, up, view_dir = camera_axes()

    zdir = unit(normal)
    # +Z voltado para a câmera, mesma regra usada na Direct.
    if zdir.dot(view_dir) > 0:
        zdir = -zdir

    xdir = right - zdir * right.dot(zdir)
    if xdir.Length < TOL:
        ydir = up - zdir * up.dot(zdir)
        if ydir.Length < TOL:
            raise ValueError("Não consegui orientar o Sketch pela vista atual.")
        ydir.normalize()
        xdir = ydir.cross(zdir)
        xdir.normalize()
    else:
        xdir.normalize()
        ydir = zdir.cross(xdir)
        ydir.normalize()

    if ydir.dot(up) < 0:
        zdir = -zdir
        ydir = zdir.cross(xdir)
        ydir.normalize()

    # Origem visual no canto inferior esquerdo do quadrilátero.
    ref = corners[0]
    scored = []
    for p in corners:
        rel = p - ref
        scored.append((p, rel.dot(xdir), rel.dot(ydir)))
    xmin = min(x[1] for x in scored)
    ymin = min(x[2] for x in scored)
    origin = min(
        scored,
        key=lambda item: (item[1] - xmin) ** 2 + (item[2] - ymin) ** 2,
    )[0]

    rot = App.Rotation(xdir, ydir, zdir, "ZXY")
    return App.Placement(origin, rot)


def to_local(placement, point):
    return placement.inverse().multVec(point)


def order_corners_in_sketch(placement, corners):
    """Ordena os quatro pontos ao redor do centro no XY local do Sketch."""
    local = [to_local(placement, p) for p in corners]
    cx = sum(p.x for p in local) / 4.0
    cy = sum(p.y for p in local) / 4.0

    indexed = list(enumerate(local))
    indexed.sort(key=lambda it: math.atan2(it[1].y - cy, it[1].x - cx))

    ordered_global = [corners[i] for i, _ in indexed]
    ordered_local = [p for _, p in indexed]
    return ordered_global, ordered_local


def unique_label(doc, base):
    labels = {getattr(o, "Label", "") for o in doc.Objects}
    if base not in labels:
        return base
    idx = 2
    while f"{base}_{idx:02d}" in labels:
        idx += 1
    return f"{base}_{idx:02d}"


def create_body_sketch(doc, guides, normal, corners):
    placement = visual_frame(normal, corners)
    _, local_points = order_corners_in_sketch(placement, corners)

    body = doc.addObject("PartDesign::Body", "Peca_Guias")
    body.Label = unique_label(doc, "Nova_Peca_Guias")
    body.Placement = placement

    sketch = body.newObject("Sketcher::SketchObject", "Sketch_Guias")
    sketch.Label = "Sketch pelas Guias"
    sketch.MapMode = "Deactivated"
    sketch.Placement = App.Placement()

    # Registra a origem de forma textual, sem App::PropertyLink para evitar
    # avisos de escopo do PartDesign.
    try:
        sketch.addProperty(
            "App::PropertyStringList",
            "UhryGuiasOrigem",
            "Direct",
            "Linhas Guia usadas para criar esta peça.",
        )
        sketch.UhryGuiasOrigem = [f"{g.Name} | {g.Label}" for g in guides]
    except Exception:
        pass

    # Garante z=0 no plano do Sketch e cria um contorno fechado.
    pts = [App.Vector(p.x, p.y, 0.0) for p in local_points]

    for i in range(4):
        a = pts[i]
        b = pts[(i + 1) % 4]
        sketch.addGeometry(Part.LineSegment(a, b), False)

    # Coincidências deixam o perfil topologicamente fechado mesmo se o usuário
    # editar o Sketch depois.
    for i in range(4):
        j = (i + 1) % 4
        try:
            sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, j, 1))
        except Exception:
            pass

    return body, sketch


def open_native_pad(body, sketch):
    """Seleciona o Sketch e abre o Pad nativo do Part Design."""
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(sketch)

    # Ajuda o Part Design a reconhecer o Body correto como ativo.
    try:
        Gui.activeDocument().activeView().setActiveObject("pdbody", body)
    except Exception:
        pass

    try:
        Gui.runCommand("PartDesign_Pad", 0)
    except Exception as e:
        raise RuntimeError(
            "O Body e o Sketch foram criados, mas não consegui abrir o Pad automaticamente.\n"
            "Selecione o Sketch e clique em Pad no Part Design.\n\n"
            f"Detalhe: {e}"
        )


def _execute():
    doc = App.ActiveDocument
    if doc is None:
        raise ValueError("Abra um documento do FreeCAD antes de usar a ferramenta.")

    guides = selected_guides()
    if len(guides) != 4:
        raise ValueError(
            "Selecione exatamente 4 Linhas Guia.\n\n"
            "A ferramenta espera 2 guias paralelas em uma direção e "
            "2 guias paralelas na outra."
        )

    lines = [guide_line(g) for g in guides]

    App.Console.PrintMessage("\n====================================\n")
    App.Console.PrintMessage("PECA PELAS GUIAS 0.2 - LEITURA GLOBAL\n")
    App.Console.PrintMessage("====================================\n")
    for line in lines:
        p = line["p"]
        d = line["d"]
        App.Console.PrintMessage(
            f"- {line['obj'].Label}: centro=({p.x:.3f}, {p.y:.3f}, {p.z:.3f}) "
            f"dir=({d.x:.6f}, {d.y:.6f}, {d.z:.6f})\n"
        )
    App.Console.PrintMessage("====================================\n")

    family_a, family_b = classify_pairs(lines)
    normal = validate_families(family_a, family_b)

    # Quatro cruzamentos entre as duas famílias.
    corners = [
        intersect_lines(family_a[0], family_b[0]),
        intersect_lines(family_a[0], family_b[1]),
        intersect_lines(family_a[1], family_b[0]),
        intersect_lines(family_a[1], family_b[1]),
    ]

    doc.openTransaction("Peça pelas Guias")
    try:
        body, sketch = create_body_sketch(doc, guides, normal, corners)
        doc.recompute()
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        doc.recompute()
        raise

    open_native_pad(body, sketch)

    App.Console.PrintMessage(
        f"[Peça pelas Guias {VERSION}] Body + Sketch criados; Pad aberto.\n"
    )




def run():
    """Entrada da bancada Direct."""
    try:
        return _execute()
    except Exception as exc:
        App.Console.PrintError(
            f"[Peça pelas Guias {VERSION}] {exc}\n"
        )
        App.Console.PrintError(traceback.format_exc())
        try:
            QtWidgets.QMessageBox.critical(
                Gui.getMainWindow(),
                f"Peça pelas Guias {VERSION}",
                str(exc),
            )
        except Exception:
            pass
        return None
