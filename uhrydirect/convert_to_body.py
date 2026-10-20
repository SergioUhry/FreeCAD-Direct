# -*- coding: utf-8 -*-

import FreeCAD as App
import FreeCADGui as Gui
from .parametric_body_base import create_base


def placement_global(obj):
    try:
        return App.Placement(obj.getGlobalPlacement())
    except Exception:
        try:
            return App.Placement(obj.Placement)
        except Exception:
            return App.Placement()


def encontrar_body(obj):
    """
    Encontra o PartDesign::Body que já contém o objeto.
    """
    if obj is None:
        return None

    if getattr(obj, "TypeId", "") == "PartDesign::Body":
        return obj

    for nome_metodo in ("getParentGeoFeatureGroup", "getParentGroup"):
        metodo = getattr(obj, nome_metodo, None)
        if callable(metodo):
            try:
                pai = metodo()
                if pai is not None and getattr(pai, "TypeId", "") == "PartDesign::Body":
                    return pai
            except Exception:
                pass

    visitados = set()
    fila = [obj]

    while fila:
        atual = fila.pop(0)
        chave = getattr(atual, "Name", str(id(atual)))

        if chave in visitados:
            continue

        visitados.add(chave)

        for pai in getattr(atual, "InList", []):
            if getattr(pai, "TypeId", "") == "PartDesign::Body":
                return pai
            fila.append(pai)

    return None


def encontrar_part_pai(obj):
    if obj is None:
        return None

    visitados = set()
    fila = [obj]

    while fila:
        atual = fila.pop(0)
        chave = getattr(atual, "Name", str(id(atual)))

        if chave in visitados:
            continue

        visitados.add(chave)

        for pai in getattr(atual, "InList", []):
            if getattr(pai, "TypeId", "") == "App::Part":
                return pai
            fila.append(pai)

    return None


def eh_sketch(obj):
    return getattr(obj, "TypeId", "") == "Sketcher::SketchObject"


def quantidade_geometria_externa(sketch):
    """
    Retorna a quantidade de projeções/interseções externas do Sketch.
    """
    try:
        return int(sketch.getExternalGeometryCount())
    except Exception:
        try:
            return len(sketch.ExternalGeometry)
        except Exception:
            return 0


def tem_shape_util(obj):
    shape = getattr(obj, "Shape", None)

    if shape is None:
        return False

    try:
        return not shape.isNull()
    except Exception:
        try:
            return len(shape.Faces) > 0
        except Exception:
            return False


def copiar_aparencia(origem, destino):
    for prop in (
        "ShapeColor",
        "LineColor",
        "PointColor",
        "Transparency",
        "DisplayMode",
    ):
        try:
            setattr(
                destino.ViewObject,
                prop,
                getattr(origem.ViewObject, prop),
            )
        except Exception:
            pass


def mover_sketch_para_body(body, sketch, global_antes):
    """
    Move um Sketch para Body preservando Placement global.
    """
    body_atual = encontrar_body(sketch)

    if body_atual == body:
        return

    body.addObject(sketch)

    pl_body_global = placement_global(body)
    sketch.Placement = (
        pl_body_global.inverse()
        * global_antes
    )


def run():
    doc = App.ActiveDocument

    if doc is None:
        App.Console.PrintError(
            "Direct — nenhum documento aberto.\n"
        )
        return False

    objetos = Gui.Selection.getSelection()

    if not objetos:
        App.Console.PrintError(
            "Direct — selecione um sólido e, opcionalmente, Sketch(es).\n"
        )
        return False

    sketches = [
        obj for obj in objetos
        if eh_sketch(obj)
    ]

    candidatos = [
        obj for obj in objetos
        if not eh_sketch(obj) and tem_shape_util(obj)
    ]

    if len(candidatos) != 1:
        App.Console.PrintError(
            "Direct — selecione exatamente UM sólido e, opcionalmente, Sketch(es).\n"
        )
        return False

    origem = candidatos[0]
    body_existente = encontrar_body(origem)

    # Proteção: um Sketch com External Geometry apontando para um sólido
    # solto não deve ser movido para um Body que substituirá esse sólido.
    # O FreeCAD 1.1.x não expõe uma troca pública simples da fonte externa
    # preservando automaticamente todos os GeoIds/constraints.
    if body_existente is None:
        sketches_com_externas = [
            sketch for sketch in sketches
            if quantidade_geometria_externa(sketch) > 0
        ]

        if sketches_com_externas:
            nomes = ", ".join(
                sketch.Label
                for sketch in sketches_com_externas
            )

            App.Console.PrintError(
                "Direct — conversão cancelada para proteger o Sketch.\n"
                "O(s) Sketch(es) {} possuem geometria externa.\n"
                "Fluxo seguro: converta primeiro somente o sólido para Body; "
                "depois use 'Desenhar na Face' no Base_Direct e faça as projeções "
                "já dentro do Body.\n".format(nomes)
            )
            return False

    # --------------------------------------------------------
    # CASO A — A PEÇA JÁ PERTENCE A UM BODY
    # --------------------------------------------------------
    if body_existente is not None:
        sketch_globals = {
            sketch.Name: placement_global(sketch)
            for sketch in sketches
        }

        doc.openTransaction(
            "Direct - Reutilizar Body existente"
        )

        try:
            for sketch in sketches:
                mover_sketch_para_body(
                    body_existente,
                    sketch,
                    sketch_globals[sketch.Name],
                )

            doc.recompute()
            doc.commitTransaction()

        except Exception as erro:
            try:
                doc.abortTransaction()
                doc.recompute()
            except Exception:
                pass

            App.Console.PrintError(
                "Direct — erro ao reutilizar Body existente:\n{}\n".format(erro)
            )
            return False

        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(body_existente)

        App.Console.PrintMessage(
            "\n"
            "====================================\n"
            "DIRECT — BODY EXISTENTE\n"
            "====================================\n"
            "Body reutilizado: {}\n"
            "Novo Body criado: NÃO\n"
            "Sketches incorporados: {}\n"
            "====================================\n".format(
                body_existente.Label,
                len(sketches),
            )
        )

        return True

    # --------------------------------------------------------
    # CASO B — SÓLIDO SOLTO/IMPORTADO
    # --------------------------------------------------------
    origem_label = getattr(origem, "Label", origem.Name)
    origem_name = origem.Name
    origem_global = placement_global(origem)
    part_pai = encontrar_part_pai(origem)

    sketch_globals = {
        sketch.Name: placement_global(sketch)
        for sketch in sketches
    }

    doc.openTransaction(
        "Direct - Converter para Body"
    )

    try:
        body = doc.addObject(
            "PartDesign::Body",
            "Body",
        )
        body.Label = origem_label

        if part_pai is not None:
            part_pai.addObject(body)

            pl_part_global = placement_global(part_pai)
            body.Placement = (
                pl_part_global.inverse()
                * origem_global
            )
        else:
            body.Placement = origem_global

        base = create_base(body, origem, copiar_aparencia)

        for sketch in sketches:
            mover_sketch_para_body(
                body,
                sketch,
                sketch_globals[sketch.Name],
            )

        doc.recompute()

        # A fonte permanece viva para conservar dimensões, expressões e histórico.

        doc.recompute()
        doc.commitTransaction()

    except Exception as erro:
        try:
            doc.abortTransaction()
            doc.recompute()
        except Exception:
            pass

        App.Console.PrintError(
            "Direct — erro ao converter para Body:\n{}\n".format(erro)
        )
        return False

    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(body)

    App.Console.PrintMessage(
        "\n"
        "====================================\n"
        "DIRECT — CONVERTER PARA BODY\n"
        "====================================\n"
        "Origem: {}\n"
        "Body criado: {}\n"
        "Base interna: Base_Direct\n"
        "Sketches incorporados: {}\n"
        "Objeto original preservado: SIM — expandir Base_Direct\n"
        "====================================\n".format(
            origem_label,
            body.Label,
            len(sketches),
        )
    )

    return True
