import FreeCAD as App
import FreeCADGui as Gui
import Part

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets


# MATRIZ DE FURACAO LEVE X/Y
#
# 1. Crie normalmente o primeiro Hole ou Pocket a partir de um unico Sketch.
# 2. Deixe esse Hole/Pocket como Tip do Body e selecione-o na arvore.
# 3. Execute esta macro e informe linhas, colunas e espacamentos.
# 4. Para editar, selecione a matriz pronta e execute a mesma macro novamente.
#
# A macro recupera o volume retirado pelo Hole/Pocket, cria suas copias em uma
# matriz e faz um unico corte booleano. O Sketch nao e duplicado. O resultado
# e um PartDesign::Feature dentro do mesmo Body.

doc = App.ActiveDocument


class DialogoMatriz(QtWidgets.QDialog):
    def __init__(
        self, nome_fonte, valores_iniciais=None,
        tamanho_furo_x=0.0, tamanho_furo_y=0.0, parent=None
    ):
        super().__init__(parent)
        valores_iniciais = valores_iniciais or {}
        self.tamanho_furo_x = float(tamanho_furo_x)
        self.tamanho_furo_y = float(tamanho_furo_y)
        self.setWindowTitle("Matriz de furacao leve X/Y")
        self.setMinimumWidth(390)

        titulo = QtWidgets.QLabel(
            "Operacao selecionada: <b>{}</b>".format(nome_fonte)
        )
        explicacao = QtWidgets.QLabel(
            "O primeiro furo corresponde a X=0 e Y=0. "
            "Valores negativos de espacamento invertem a direcao."
        )
        explicacao.setWordWrap(True)

        self.quantidade_x = QtWidgets.QSpinBox()
        self.quantidade_x.setRange(1, 1000)
        self.quantidade_x.setValue(int(valores_iniciais.get("nx", 4)))

        self.quantidade_y = QtWidgets.QSpinBox()
        self.quantidade_y.setRange(1, 1000)
        self.quantidade_y.setValue(int(valores_iniciais.get("ny", 3)))

        self.espacamento_x = QtWidgets.QDoubleSpinBox()
        self.espacamento_x.setRange(-1000000.0, 1000000.0)
        self.espacamento_x.setDecimals(3)
        self.espacamento_x.setSuffix(" mm")
        self.espacamento_x.setValue(float(valores_iniciais.get("dx", 100.0)))

        self.espacamento_y = QtWidgets.QDoubleSpinBox()
        self.espacamento_y.setRange(-1000000.0, 1000000.0)
        self.espacamento_y.setDecimals(3)
        self.espacamento_y.setSuffix(" mm")
        self.espacamento_y.setValue(float(valores_iniciais.get("dy", 100.0)))

        self.centralizar = QtWidgets.QCheckBox(
            "Centralizar a matriz em torno do primeiro furo"
        )
        self.centralizar.setChecked(
            bool(valores_iniciais.get("centralizar", False))
        )

        formulario = QtWidgets.QFormLayout()
        formulario.addRow("Quantidade em X:", self.quantidade_x)
        formulario.addRow("Espacamento em X:", self.espacamento_x)
        formulario.addRow("Quantidade em Y:", self.quantidade_y)
        formulario.addRow("Espacamento em Y:", self.espacamento_y)

        self.resumo = QtWidgets.QLabel()
        self.resumo.setStyleSheet("font-weight: bold;")
        self.medidas = QtWidgets.QLabel()
        self.medidas.setWordWrap(True)
        self.medidas.setStyleSheet(
            "padding: 7px; background: #e8f2ff; border: 1px solid #7ba7d9;"
        )

        botoes = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(titulo)
        layout.addWidget(explicacao)
        layout.addSpacing(8)
        layout.addLayout(formulario)
        layout.addWidget(self.centralizar)
        layout.addWidget(self.resumo)
        layout.addWidget(self.medidas)
        layout.addWidget(botoes)

        self.quantidade_x.valueChanged.connect(self.atualizar_resumo)
        self.quantidade_y.valueChanged.connect(self.atualizar_resumo)
        self.espacamento_x.valueChanged.connect(self.atualizar_resumo)
        self.espacamento_y.valueChanged.connect(self.atualizar_resumo)
        self.atualizar_resumo()

    def atualizar_resumo(self):
        nx = self.quantidade_x.value()
        ny = self.quantidade_y.value()
        dx = abs(self.espacamento_x.value())
        dy = abs(self.espacamento_y.value())
        total = nx * ny
        centros_x = max(nx - 1, 0) * dx
        centros_y = max(ny - 1, 0) * dy
        ocupado_x = centros_x + self.tamanho_furo_x
        ocupado_y = centros_y + self.tamanho_furo_y
        self.resumo.setText("Total de furos: {}".format(total))
        self.medidas.setText(
            (
                "<b>Extensao da matriz</b><br>"
                "X — centros extremos: {:.3f} mm | total ocupado: {:.3f} mm<br>"
                "Y — centros extremos: {:.3f} mm | total ocupado: {:.3f} mm"
            ).format(centros_x, ocupado_x, centros_y, ocupado_y)
        )

    def valores(self):
        return {
            "nx": self.quantidade_x.value(),
            "ny": self.quantidade_y.value(),
            "dx": self.espacamento_x.value(),
            "dy": self.espacamento_y.value(),
            "centralizar": self.centralizar.isChecked(),
        }


def executar_dialogo(dialogo):
    if hasattr(dialogo, "exec"):
        return dialogo.exec()
    return dialogo.exec_()


def body_contem(obj):
    if obj.TypeId == "PartDesign::Body":
        return obj
    for pai in getattr(obj, "InList", []):
        if pai.TypeId == "PartDesign::Body":
            return pai
    return None


def resolver_link(valor):
    if isinstance(valor, (tuple, list)):
        return valor[0] if valor else None
    return valor


def recurso_anterior(body, fonte):
    base = resolver_link(getattr(fonte, "BaseFeature", None))
    if base is not None and hasattr(base, "Shape") and not base.Shape.isNull():
        return base

    objetos = list(getattr(body, "Group", []))
    try:
        indice = objetos.index(fonte)
    except ValueError:
        indice = len(objetos)

    for candidato in reversed(objetos[:indice]):
        if not hasattr(candidato, "Shape"):
            continue
        try:
            if not candidato.Shape.isNull() and len(candidato.Shape.Solids) > 0:
                return candidato
        except Exception:
            pass
    return None


def perfil_da_operacao(fonte):
    for propriedade in ("Profile", "SketchBased"):
        perfil = resolver_link(getattr(fonte, propriedade, None))
        if perfil is not None and hasattr(perfil, "Placement"):
            return perfil
    return None


def eixos_da_matriz(fonte):
    perfil = perfil_da_operacao(fonte)
    if perfil is None:
        App.Console.PrintWarning(
            "Sketch de origem nao localizado; usando os eixos X/Y do Body.\n"
        )
        return App.Vector(1, 0, 0), App.Vector(0, 1, 0), None

    rotacao = perfil.Placement.Rotation
    eixo_x = rotacao.multVec(App.Vector(1, 0, 0))
    eixo_y = rotacao.multVec(App.Vector(0, 1, 0))
    eixo_x.normalize()
    eixo_y.normalize()
    return eixo_x, eixo_y, perfil


def volume_ferramenta(base, fonte):
    ferramenta = base.Shape.cut(fonte.Shape)
    if ferramenta.isNull() or len(ferramenta.Solids) < 1:
        raise ValueError(
            "Nao consegui recuperar o volume removido pela operacao selecionada."
        )
    tolerancia_volume = max(abs(base.Shape.Volume) * 1.0e-10, 1.0e-9)
    if ferramenta.Volume <= tolerancia_volume:
        raise ValueError(
            "A diferenca entre o recurso anterior e o Hole/Pocket e muito pequena."
        )
    return ferramenta


def tamanho_ferramenta_nos_eixos(ferramenta, eixo_x, eixo_y):
    """Mede a ocupacao do furo nos eixos locais da matriz."""
    diagonal = max(float(ferramenta.BoundBox.DiagonalLength), 1.0)
    deflexao = max(diagonal * 1.0e-4, 0.005)
    pontos, _ = ferramenta.tessellate(deflexao)
    if not pontos:
        pontos = [vertice.Point for vertice in ferramenta.Vertexes]
    proj_x = [ponto.dot(eixo_x) for ponto in pontos]
    proj_y = [ponto.dot(eixo_y) for ponto in pontos]
    return max(proj_x) - min(proj_x), max(proj_y) - min(proj_y)


def medidas_da_matriz(parametros, tamanho_furo_x, tamanho_furo_y):
    centros_x = max(parametros["nx"] - 1, 0) * abs(parametros["dx"])
    centros_y = max(parametros["ny"] - 1, 0) * abs(parametros["dy"])
    return {
        "tamanho_furo_x": tamanho_furo_x,
        "tamanho_furo_y": tamanho_furo_y,
        "centros_x": centros_x,
        "centros_y": centros_y,
        "total_x": centros_x + tamanho_furo_x,
        "total_y": centros_y + tamanho_furo_y,
    }


def criar_cortadores(ferramenta, eixo_x, eixo_y, parametros):
    nx = parametros["nx"]
    ny = parametros["ny"]
    dx = parametros["dx"]
    dy = parametros["dy"]

    origem_x = -0.5 * (nx - 1) * dx if parametros["centralizar"] else 0.0
    origem_y = -0.5 * (ny - 1) * dy if parametros["centralizar"] else 0.0

    cortadores = []
    for iy in range(ny):
        for ix in range(nx):
            deslocamento = (
                eixo_x * (origem_x + ix * dx)
                + eixo_y * (origem_y + iy * dy)
            )
            copia = ferramenta.copy()
            copia.translate(deslocamento)
            cortadores.append(copia)
    return cortadores


def cortar_em_conjunto(forma_base, cortadores):
    composto = Part.makeCompound(cortadores)
    resultado = forma_base.cut(composto)

    if resultado.isNull() or not resultado.isValid() or len(resultado.Solids) < 1:
        # Alternativa para versoes do OpenCASCADE que nao cortam Compound bem.
        ferramenta_unida = cortadores[0]
        if len(cortadores) > 1:
            ferramenta_unida = ferramenta_unida.multiFuse(cortadores[1:])
        resultado = forma_base.cut(ferramenta_unida)

    try:
        resultado = resultado.removeSplitter()
    except Exception:
        pass

    if resultado.isNull() or not resultado.isValid():
        raise ValueError("O corte conjunto produziu uma forma invalida.")
    if len(resultado.Solids) != 1:
        raise ValueError(
            "A matriz separou o Body em mais de um solido. A operacao foi cancelada."
        )
    if resultado.Volume >= forma_base.Volume - 1.0e-9:
        raise ValueError(
            "Nenhum dos furos intersectou o Body. Confira direcoes e espacamentos."
        )
    return resultado


def nome_livre(base):
    nome = base
    contador = 1
    while doc.getObject(nome) is not None:
        nome = "{}_{}".format(base, contador)
        contador += 1
    return nome


def copiar_aparencia(origem, destino):
    for atributo in (
        "ShapeColor", "LineColor", "PointColor", "Transparency",
        "LineWidth", "PointSize",
    ):
        try:
            setattr(destino.ViewObject, atributo, getattr(origem.ViewObject, atributo))
        except Exception:
            pass


def garantir_propriedade(obj, tipo, nome, grupo="Matriz"):
    if nome not in obj.PropertiesList:
        obj.addProperty(tipo, nome, grupo)


def numero_propriedade(valor):
    return float(valor.Value) if hasattr(valor, "Value") else float(valor)


def e_matriz_editavel(obj):
    exigidas = (
        "OperacaoOriginal", "BaseOriginal", "QuantidadeX", "QuantidadeY",
        "EspacamentoX", "EspacamentoY", "DirecaoX", "DirecaoY",
    )
    return all(nome in getattr(obj, "PropertiesList", []) for nome in exigidas)


def matriz_existente_para_fonte(fonte):
    """Localiza a matriz mais recente que usa o Hole/Pocket selecionado."""
    body = body_contem(fonte)
    if body is None:
        return None

    candidatas = []
    for obj in getattr(body, "Group", []):
        if not e_matriz_editavel(obj):
            continue
        try:
            if resolver_link(obj.OperacaoOriginal) == fonte:
                candidatas.append(obj)
        except Exception:
            pass

    if not candidatas:
        return None
    if body.Tip in candidatas:
        return body.Tip
    return candidatas[-1]


def parametros_da_matriz(obj):
    dx = numero_propriedade(obj.EspacamentoX)
    dy = numero_propriedade(obj.EspacamentoY)
    if "PassoXAssinado" in obj.PropertiesList:
        dx = float(obj.PassoXAssinado)
    if "PassoYAssinado" in obj.PropertiesList:
        dy = float(obj.PassoYAssinado)
    return {
        "nx": int(obj.QuantidadeX),
        "ny": int(obj.QuantidadeY),
        "dx": dx,
        "dy": dy,
        "centralizar": bool(obj.Centralizada),
    }


def gravar_parametros(obj, parametros, eixo_x, eixo_y, medidas=None):
    garantir_propriedade(obj, "App::PropertyInteger", "QuantidadeX")
    garantir_propriedade(obj, "App::PropertyInteger", "QuantidadeY")
    garantir_propriedade(obj, "App::PropertyLength", "EspacamentoX")
    garantir_propriedade(obj, "App::PropertyLength", "EspacamentoY")
    garantir_propriedade(obj, "App::PropertyFloat", "PassoXAssinado")
    garantir_propriedade(obj, "App::PropertyFloat", "PassoYAssinado")
    garantir_propriedade(obj, "App::PropertyBool", "Centralizada")
    garantir_propriedade(obj, "App::PropertyVector", "DirecaoX")
    garantir_propriedade(obj, "App::PropertyVector", "DirecaoY")

    obj.QuantidadeX = parametros["nx"]
    obj.QuantidadeY = parametros["ny"]
    obj.EspacamentoX = abs(parametros["dx"])
    obj.EspacamentoY = abs(parametros["dy"])
    obj.PassoXAssinado = parametros["dx"]
    obj.PassoYAssinado = parametros["dy"]
    obj.Centralizada = parametros["centralizar"]
    obj.DirecaoX = eixo_x
    obj.DirecaoY = eixo_y

    if medidas is not None:
        for nome in (
            "TamanhoFuroX", "TamanhoFuroY", "DistanciaCentrosX",
            "DistanciaCentrosY", "ComprimentoTotalX", "ComprimentoTotalY",
        ):
            garantir_propriedade(obj, "App::PropertyLength", nome, "Medidas")
        obj.TamanhoFuroX = medidas["tamanho_furo_x"]
        obj.TamanhoFuroY = medidas["tamanho_furo_y"]
        obj.DistanciaCentrosX = medidas["centros_x"]
        obj.DistanciaCentrosY = medidas["centros_y"]
        obj.ComprimentoTotalX = medidas["total_x"]
        obj.ComprimentoTotalY = medidas["total_y"]


def criar_recurso(
    body, base, fonte, perfil, resultado, parametros,
    eixo_x, eixo_y, medidas
):
    novo = body.newObject(
        "PartDesign::Feature", nome_livre("MatrizFuracaoLeve")
    )
    novo.Label = "Matriz de furacao leve {}x{}".format(
        parametros["nx"], parametros["ny"]
    )
    novo.Shape = resultado

    novo.addProperty("App::PropertyLink", "OperacaoOriginal", "Matriz")
    novo.OperacaoOriginal = fonte
    novo.addProperty("App::PropertyLink", "BaseOriginal", "Matriz")
    novo.BaseOriginal = base
    if perfil is not None:
        novo.addProperty("App::PropertyLink", "SketchOriginal", "Matriz")
        novo.SketchOriginal = perfil

    gravar_parametros(novo, parametros, eixo_x, eixo_y, medidas)
    novo.addProperty("App::PropertyString", "Observacao", "Matriz")
    novo.Observacao = (
        "Para editar, selecione esta matriz e execute novamente a macro "
        "Matriz_Furacao_Leve."
    )

    copiar_aparencia(fonte, novo)
    fonte.ViewObject.Visibility = False
    body.Tip = novo
    return novo


def atualizar_recurso(
    matriz, resultado, parametros, eixo_x, eixo_y, medidas
):
    matriz.Shape = resultado
    matriz.Label = "Matriz de furacao leve {}x{}".format(
        parametros["nx"], parametros["ny"]
    )
    gravar_parametros(matriz, parametros, eixo_x, eixo_y, medidas)
    if "Observacao" in matriz.PropertiesList:
        matriz.Observacao = (
            "Para editar, selecione esta matriz e execute novamente a macro "
            "Matriz_Furacao_Leve."
        )
    return matriz


def validar_fonte(fonte):
    tipos_permitidos = ("PartDesign::Hole", "PartDesign::Pocket")
    if fonte.TypeId not in tipos_permitidos:
        raise ValueError(
            "Selecione na arvore um Hole ou Pocket do Part Design. "
            "Tipo selecionado: {}.".format(fonte.TypeId)
        )

    body = body_contem(fonte)
    if body is None:
        raise ValueError("O Hole/Pocket selecionado nao pertence a um Body.")
    if body.Tip != fonte:
        raise ValueError(
            "O Hole/Pocket precisa ser o ultimo recurso (Tip) do Body. "
            "Isso evita apagar operacoes criadas depois dele."
        )
    base = recurso_anterior(body, fonte)
    if base is None:
        raise ValueError("Nao encontrei o recurso anterior ao Hole/Pocket.")
    return body, base


def validar_matriz(matriz):
    if not e_matriz_editavel(matriz):
        raise ValueError(
            "Selecione um Hole, Pocket ou uma Matriz de furacao leve."
        )
    body = body_contem(matriz)
    if body is None:
        raise ValueError("A matriz selecionada nao pertence a um Body.")
    if body.Tip != matriz:
        raise ValueError(
            "A matriz precisa ser o ultimo recurso (Tip) do Body para ser editada."
        )
    fonte = resolver_link(matriz.OperacaoOriginal)
    base = resolver_link(matriz.BaseOriginal)
    if fonte is None or base is None:
        raise ValueError("Os links da operacao original foram perdidos.")
    if not hasattr(base, "Shape") or base.Shape.isNull():
        raise ValueError("A forma base original nao esta mais disponivel.")
    return body, base, fonte


def validar_parametros(parametros):
    total = parametros["nx"] * parametros["ny"]
    if total < 2:
        raise ValueError("A matriz precisa ter pelo menos duas ocorrencias.")
    if parametros["nx"] > 1 and abs(parametros["dx"]) < 1.0e-9:
        raise ValueError("O espacamento X nao pode ser zero.")
    if parametros["ny"] > 1 and abs(parametros["dy"]) < 1.0e-9:
        raise ValueError("O espacamento Y nao pode ser zero.")
    return total


def imprimir_resultado(body, fonte, resultado, parametros, medidas, editado):
    total = parametros["nx"] * parametros["ny"]
    App.Console.PrintMessage(
        (
            "\n====================================\n"
            "MATRIZ DE FURACAO LEVE\n"
            "====================================\n"
            "Modo: {}\nBody: {}\nOperacao original: {}\nResultado: {}\n"
            "Quantidade X: {}\nQuantidade Y: {}\nTotal: {} furos\n"
            "Espacamento X: {:.3f} mm\nEspacamento Y: {:.3f} mm\n"
            "Centros extremos X: {:.3f} mm\nCentros extremos Y: {:.3f} mm\n"
            "Comprimento total X: {:.3f} mm\nComprimento total Y: {:.3f} mm\n"
            "Sketch duplicado: NAO\nCorte booleano conjunto: SIM\n"
            "Operacao original preservada: SIM\n"
            "====================================\n"
        ).format(
            "EDICAO" if editado else "CRIACAO",
            body.Label, fonte.Label, resultado.Label,
            parametros["nx"], parametros["ny"], total,
            parametros["dx"], parametros["dy"],
            medidas["centros_x"], medidas["centros_y"],
            medidas["total_x"], medidas["total_y"],
        )
    )


if doc is None:
    App.Console.PrintError("Nenhum documento aberto.\n")
else:
    selecionados = Gui.Selection.getSelection()
    if len(selecionados) != 1:
        App.Console.PrintError(
            "Selecione um Hole/Pocket para criar ou uma matriz para editar.\n"
        )
    else:
        selecionado = selecionados[0]
        try:
            editando = e_matriz_editavel(selecionado)
            if not editando:
                matriz_encontrada = matriz_existente_para_fonte(selecionado)
                if matriz_encontrada is not None:
                    App.Console.PrintMessage(
                        "Matriz existente localizada para '{}'. Abrindo em modo de edicao.\n".format(
                            selecionado.Label
                        )
                    )
                    selecionado = matriz_encontrada
                    editando = True

            if editando:
                matriz = selecionado
                body, base, fonte = validar_matriz(matriz)
                iniciais = parametros_da_matriz(matriz)
                eixo_x = App.Vector(matriz.DirecaoX)
                eixo_y = App.Vector(matriz.DirecaoY)
                eixo_x.normalize()
                eixo_y.normalize()
                perfil = resolver_link(getattr(matriz, "SketchOriginal", None))
                nome_dialogo = matriz.Label + " (editar)"
            else:
                matriz = None
                fonte = selecionado
                body, base = validar_fonte(fonte)
                iniciais = None
                eixo_x, eixo_y, perfil = eixos_da_matriz(fonte)
                nome_dialogo = fonte.Label + " (criar matriz)"

            ferramenta = volume_ferramenta(base, fonte)
            tamanho_furo_x, tamanho_furo_y = tamanho_ferramenta_nos_eixos(
                ferramenta, eixo_x, eixo_y
            )
            dialogo = DialogoMatriz(
                nome_dialogo, iniciais, tamanho_furo_x, tamanho_furo_y,
                Gui.getMainWindow()
            )
            if executar_dialogo(dialogo):
                parametros = dialogo.valores()
                validar_parametros(parametros)
                medidas = medidas_da_matriz(
                    parametros, tamanho_furo_x, tamanho_furo_y
                )

                acao = "Editar" if editando else "Criar"
                doc.openTransaction(acao + " matriz de furacao leve")
                try:
                    cortadores = criar_cortadores(
                        ferramenta, eixo_x, eixo_y, parametros
                    )
                    forma_resultado = cortar_em_conjunto(base.Shape, cortadores)
                    if editando:
                        novo = atualizar_recurso(
                            matriz, forma_resultado, parametros,
                            eixo_x, eixo_y, medidas
                        )
                    else:
                        novo = criar_recurso(
                            body, base, fonte, perfil, forma_resultado,
                            parametros, eixo_x, eixo_y, medidas
                        )
                    doc.recompute()
                    doc.commitTransaction()

                    Gui.Selection.clearSelection()
                    Gui.Selection.addSelection(novo)
                    imprimir_resultado(
                        body, fonte, novo, parametros, medidas, editando
                    )
                except Exception:
                    doc.abortTransaction()
                    raise
        except Exception as erro:
            App.Console.PrintError(
                "\nErro na matriz de furacao:\n{}\n\n".format(erro)
            )
