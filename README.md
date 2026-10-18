# Direct

Workbench para FreeCAD voltada a modelagem direta, criação e edição de peças, posicionamento, linhas guia, medição e matrizes.

**Versão:** 0.9.12
**FreeCAD:** 1.1+

## Objetivo

A Direct reúne ferramentas para acelerar tarefas de modelagem e montagem mantendo compatibilidade com os recursos nativos do FreeCAD. Os comandos priorizam fluxos curtos, preservação da posição global e baixa dependência topológica entre peças.

## Conteúdo

- [Objetivo](#objetivo)
- [Instalação](#instalação)
- [Ferramentas](#ferramentas)
  - [Extrudar Face](#extrudar-face)
  - [Desenhar na Face](#desenhar-na-face)
  - [Converter para Body](#converter-para-body)
  - [Mover por Pontos](#mover-por-pontos)
  - [Manipulador](#manipulador)
  - [Posicionar Peça](#posicionar-peça)
  - [Linha Guia](#linha-guia)
  - [Snap Cruzamento de Guias](#snap-cruzamento-de-guias)
  - [Peça pelas Guias](#peça-pelas-guias)
  - [Medidor XYZ Pro](#medidor-xyz-pro)
  - [Matriz Leve](#matriz-leve)
  - [Matriz de Furação](#matriz-de-furação)
  - [Mover na Árvore](#mover-na-árvore)
- [Regras de seleção e posição](#regras-de-seleção-e-posição)
- [Alterações da versão 0.9.12](#alterações-da-versão-0912)
- [Compatibilidade](#compatibilidade)
- [Licença](#licença)

## Instalação

### Instalação manual

Copie a pasta `Direct` para o diretório de módulos do usuário do FreeCAD e reinicie o programa.

Linux:

```text
~/.local/share/FreeCAD/Mod/
```

A estrutura deve ficar semelhante a:

```text
Mod/
└── Direct/
    ├── Init.py
    ├── InitGui.py
    ├── package.xml
    ├── Resources/
    └── uhrydirect/
```

Depois de reiniciar o FreeCAD, selecione a bancada **Direct** no seletor de Workbenches.

## Ferramentas

### Extrudar Face

Cria uma extrusão diretamente a partir de uma face plana selecionada, usando a própria face como perfil para um novo Pad, em um fluxo de extrusão direta semelhante ao Push/Pull.

**Como usar**

1. Selecione exatamente uma face plana.
2. Execute **Extrudar Face**.
3. A Direct identifica se a face já pertence a um `PartDesign::Body`.
4. O contorno completo da face é copiado para um novo `Sketch` interno e independente (`MapMode = Deactivated`).
5. O comando nativo **Pad** é aberto imediatamente para definir o comprimento, sentido e demais parâmetros da extrusão.

**Quando a face já pertence a um Body**

- o Body existente é preservado e reutilizado;
- nenhum novo Body é criado;
- o objeto original não é removido;
- o novo Sketch entra no mesmo Body e o Pad continua a sequência Part Design da peça.

**Quando a face pertence a um objeto fora de Body**

- o objeto é convertido automaticamente para `PartDesign::Body`;
- a geometria original é preservada em uma base interna `Base_Direct`;
- posição e aparência são preservadas sempre que compatíveis;
- o objeto solto anterior é removido somente depois que a conversão é concluída;
- o Sketch da face é criado dentro desse novo Body;
- o Pad é aberto imediatamente.

**Perfil da face**

O contorno da face selecionada é copiado como geometria normal do Sketch, portanto ele é usado diretamente pelo Pad. Faces com furos preservam os contornos internos. Linhas e círculos/arcos comuns são copiados diretamente; curvas não suportadas pelo Sketch são aproximadas por segmentos.

**Diferença para Desenhar na Face**

- **Extrudar Face** usa a própria face inteira como perfil e abre o Pad imediatamente.
- **Desenhar na Face** cria uma nova peça independente e abre o Sketcher para desenhar outro perfil; o contorno da face entra apenas como geometria de construção.

---

### Desenhar na Face

Cria rapidamente uma **nova peça independente** usando uma face existente apenas como referência geométrica.

**Como usar**

1. Selecione exatamente uma face.
2. Execute **Desenhar na Face**.
3. A Direct cria um novo `PartDesign::Body` com um `Sketch` independente no plano da face.
4. Desenhe o perfil e feche o Sketch.
5. Os objetos ocultados temporariamente reaparecem.
6. O comando nativo **Pad** é aberto automaticamente para configurar a extrusão.

**Comportamento**

- o Sketch **não é inserido no Body da peça usada como referência**;
- é criado um novo Body, preferencialmente dentro do mesmo `App::Part` da peça de referência;
- o Sketch usa `MapMode = Deactivated`;
- o contorno da face selecionada já entra no Sketch como **geometria de construção**;
- essas referências são cópias estáticas, portanto não criam link externo entre Bodies;
- não existe vínculo topológico com a face selecionada;
- a origem é posicionada no canto inferior esquerdo local da face;
- durante a edição, sólidos que estejam à frente do plano de trabalho na vista atual são ocultados temporariamente;
- Linhas Guia, Sketches e a própria peça de referência permanecem disponíveis;
- ao sair da edição do Sketch, somente os objetos ocultados pela ferramenta são restaurados;
- se o Sketch possuir geometria, o **Pad** abre automaticamente já no novo Body;
- se o Sketch for fechado vazio, nenhum Pad é criado.

A ferramenta foi pensada para iniciar uma nova peça apoiada visualmente em outra sem criar dependência entre os dois Bodies. O contorno projetado da face é inserido como construção para servir de referência durante o desenho, mas não é usado pelo Pad.

---

### Converter para Body

Converte um sólido comum ou importado em uma estrutura utilizável pelo Part Design.

**Como usar**

1. Selecione um sólido.
2. Opcionalmente, selecione também Sketches que devam acompanhar a peça.
3. Execute **Converter para Body**.

**Comportamento**

- cria um `PartDesign::Body` quando o sólido ainda não pertence a um Body;
- cria uma base interna `Base_Direct` para o sólido convertido;
- preserva a posição global da geometria;
- preserva propriedades visuais compatíveis;
- se o sólido já pertence a um Body, reutiliza o Body existente em vez de criar outro;
- Sketches selecionados podem ser incorporados ao mesmo Body preservando sua posição.

**Proteção de geometria externa**

Se um Sketch selecionado possui External Geometry apontando para um sólido que ainda está fora de Body, a conversão conjunta é cancelada. O fluxo seguro é:

1. converter somente o sólido;
2. usar **Desenhar na Face** no `Base_Direct`;
3. criar as projeções já dentro do Body.

---

### Mover por Pontos

Move ou copia objetos usando o fluxo do comando Move do Draft, com tratamento estrutural específico para Part Design.

**Como usar**

1. Selecione o objeto ou geometria da peça.
2. Execute **Mover por Pontos**.
3. Escolha o ponto-base.
4. Escolha o ponto-destino ou use a entrada numérica do Draft.

A ferramenta mantém a interface e os recursos do Draft Move, incluindo snap, restrições, campos X/Y/Z e modo de cópia.

Com **Snap Cruzamento de Guias** ativo, o Mover por Pontos recebe diretamente o cruzamento exato calculado pela Direct. O Snap Direct pode ser ligado e desligado durante o próprio comando Move; enquanto estiver ligado, os snaps nativos ficam temporariamente bloqueados.

**Regra estrutural**

| Seleção | Objeto movido ou copiado |
|---|---|
| `App::Part` | Part inteiro |
| `PartDesign::Body` | Body inteiro |
| Pad, Pocket, Sketch, Fillet, Chamfer ou outra feature dentro de Body | Body pai inteiro |
| objeto simples fora de Body | somente o objeto |
| `App::Link` | a ocorrência do Link |

Uma feature interna de Body não é movida ou copiada isoladamente.

**Cópia**

O modo Copy e os atalhos oferecidos pelo Draft continuam disponíveis. A cópia é aplicada ao objeto lógico resolvido pela regra acima.

---

### Manipulador

Abre o Transform Manipulator nativo do FreeCAD para o objeto selecionado.

**Como usar**

1. Selecione exatamente um objeto.
2. Execute **Manipulador**.
3. Use os controles nativos de translação e rotação.

A ferramenta funciona como um acesso direto ao manipulador nativo e mantém seus modos Local/Global e eixos U/V/W conforme disponibilizados pelo FreeCAD.

---

### Posicionar Peça

Posiciona uma peça usando duas referências geométricas.

**Ordem da seleção**

1. primeira referência: pertence à peça que será movida;
2. segunda referência: destino.

Depois execute **Posicionar Peça**.

#### Face → Face

Quando as duas referências são faces:

- a peça é transladada e rotacionada automaticamente;
- as faces são colocadas coincidentes;
- as normais ficam opostas;
- o ponto/canto usado como referência é escolhido próximo ao local clicado na face.

#### Ponto → Ponto

Quando a seleção não é Face → Face, a ferramenta resolve um ponto para cada referência e faz a translação entre eles.

- vértice: usa o vértice selecionado;
- aresta: usa um dos extremos, priorizando o extremo mais próximo do clique;
- face: usa o canto mais próximo do clique.

A orientação da peça é preservada no modo Ponto → Ponto.

#### Linha Guia

Cria referências geométricas e também funciona como ferramenta de medição rápida diretamente no 3D.

A ferramenta trabalha somente no **modo direto**. A antiga janela de criação e gerenciamento de guias foi retirada da interface.

#### Uso

1. Selecione exatamente uma aresta reta ou uma Linha Guia existente.
2. Execute **Linha Guia**.
3. Mova o cursor para o lado desejado.
4. Confirme com clique esquerdo ou digite uma medida e pressione `Enter`.

Se o comando for executado sem uma única referência válida selecionada, nenhuma janela é aberta. A barra de status informa que é necessário selecionar uma aresta reta ou uma Linha Guia.

#### Controles

| Ação | Resultado |
|---|---|
| mover o mouse | pré-visualiza a posição e atualiza a medida |
| `X`, `Y` ou `Z` | trava o deslocamento no eixo global correspondente |
| digitar um valor | informa a distância numericamente |
| `Enter` | confirma o valor informado |
| clique esquerdo | confirma a guia na posição atual |
| `Esc` | cancela |
| clique direito | cancela |

#### Medição e captura

- a medida aparece ao vivo junto ao cursor;
- a linha fantasma acompanha o ponteiro;
- é possível medir sem criar a guia enquanto não houver confirmação;
- a captura considera arestas válidas no plano ativo;
- cruzamentos reais entre Linhas Guia podem ser usados como referência;
- as travas X/Y/Z permitem medições em referências globais;
- Linhas Guia que tenham sido reposicionadas são lidas na posição global atual;
- o preview não altera a geometria do documento durante o movimento do mouse.

A caixa de medida informa o valor atual e o contexto de captura quando disponível.

---

### Snap Cruzamento de Guias

Snap dedicado aos cruzamentos geométricos reais entre Linhas Guia.

O Snap Direct **sempre inicia desligado** ao carregar a bancada. Ele deve ser ativado somente quando for necessário trabalhar exclusivamente com cruzamentos de guias.

#### Modo exclusivo

Ao ativar **Snap Cruzamento de Guias**:

- o estado atual dos snaps nativos do Draft/BIM é salvo;
- Endpoint, Midpoint, Near, Intersection, Lock e outros snaps nativos são temporariamente desligados e bloqueados;
- somente os cruzamentos válidos entre Linhas Guia ficam disponíveis para captura;
- o Draft Snapper continua funcionando internamente, para que comandos como **Mover por Pontos** permaneçam operacionais.

Ao desligar o Snap Direct:

- o bloqueio é removido;
- os snaps nativos voltam a ficar disponíveis;
- os modos que estavam ativos antes são restaurados automaticamente.

#### Durante Mover por Pontos

O Snap Direct pode ser ligado ou desligado **com o comando Mover por Pontos já aberto**.

Fluxo recomendado:

1. inicie **Mover por Pontos**;
2. ative **Snap Cruzamento de Guias**;
3. aproxime o cursor do cruzamento desejado;
4. quando o cursor entra na zona de captura, o marcador do Direct aparece;
5. o rodapé passa a indicar `SNAP GUIAS: CRUZAMENTO`;
6. o ponto matemático exato do cruzamento é entregue diretamente ao comando Move;
7. clique para confirmar o ponto.

Quando o cursor está fora da zona de captura, o rodapé permanece em `SNAP GUIAS: EXCLUSIVO`.

#### Validação do cruzamento

- somente interseções 3D reais são aceitas;
- linhas que apenas parecem se cruzar na projeção da tela são ignoradas;
- a captura ocorre quando o cursor chega próximo do ponto projetado na viewport;
- o número de cruzamentos disponíveis é recalculado a partir das Linhas Guia existentes;
- a ativação do Snap Direct não altera permanentemente as preferências de snap do usuário.

#### Uso fora do Mover por Pontos

Quando usado para selecionar um cruzamento como referência para outras ferramentas da Direct, o Snap pode criar um ponto temporário de seleção. Esse objeto é apenas auxiliar e não substitui a geometria das Linhas Guia.

**Resumo do estado**

| Estado | Snaps nativos | Snap de cruzamento |
|---|---|---|
| Direct desligado | disponíveis normalmente | desligado |
| Direct ligado | temporariamente bloqueados | exclusivo |
| Direct desligado novamente | estado anterior restaurado | desligado |

---

### Peça pelas Guias

Cria a base de uma nova peça a partir de quatro Linhas Guia.

**Como usar**

1. selecione exatamente quatro Linhas Guia coplanares;
2. as quatro guias devem formar dois pares de linhas paralelas;
3. execute **Peça pelas Guias**;
4. a ferramenta calcula os quatro cruzamentos;
5. cria um novo `PartDesign::Body` e um `Sketch` fechado;
6. abre o Pad nativo do Part Design para informar a extrusão.

**Características**

- os cruzamentos são calculados matematicamente;
- não depende de snap visual;
- as guias são lidas em coordenadas globais;
- o Sketch criado não mantém links externos com as guias;
- a geometria da peça é definida no momento da criação.

A ferramenta rejeita configurações em que as quatro guias não formem dois pares paralelos coplanares válidos.

---

### Medidor XYZ Pro

Painel acoplável para medir a menor distância entre duas geometrias e decompor o resultado nos eixos globais.

O painel abre no lado esquerdo da interface.

**Como usar**

1. selecione exatamente dois elementos com `Ctrl`;
2. clique em **Medir Seleção**;
3. leia os valores 3D, X, Y e Z.

**Seleções suportadas**

- faces;
- arestas;
- vértices;
- objetos inteiros;
- `App::Part`;
- `PartDesign::Body`;
- `App::Link`.

Para arestas circulares e arcos circulares, o centro do círculo é usado como ponto de medição.

**Resultados**

- `3D`: distância espacial entre os pontos mais próximos;
- `X`: componente global ΔX;
- `Y`: componente global ΔY;
- `Z`: componente global ΔZ.

#### Cotas de conferência

As caixas ao lado de 3D, X, Y e Z definem quais cotas serão criadas.

- **Criar cotas** adiciona as cotas marcadas ao modelo 3D;
- `Ctrl+Alt+D` executa o mesmo comando;
- **Apagar** remove as cotas criadas pelo Medidor;
- as cotas ficam salvas no documento e podem ser reposicionadas.

---

### Matriz Leve

Cria matrizes ortogonais leves usando Draft Link Array e mantém informações próprias de dimensão total.

**Como usar**

1. selecione uma peça, Body, Part ou uma Matriz Leve existente;
2. execute **Matriz Leve**;
3. informe quantidades e medidas nos eixos X, Y e Z;
4. confirme a criação.

**Modos de entrada**

- **Intervalo entre posições**: informa diretamente o passo entre as ocorrências;
- **Vão entre limites externos**: informa o espaço livre entre peças/conjuntos;
- **Total desejado**: informa a dimensão total final e a ferramenta calcula o intervalo.

A relação usada é:

```text
Total = tamanho da origem + intervalo × (quantidade - 1)
```

**Par oposto / Face oposta**

Permite criar um par formado pela peça original e uma segunda posição espelhada.

- escolhe-se o eixo X, Y ou Z;
- a segunda posição usa espelhamento nativo;
- as faces extremas internas ficam frente a frente;
- o intervalo lógico e a dimensão total permanecem controlados pela ferramenta.

**Matriz sobre matriz**

Uma Matriz Leve existente pode ser usada como origem de outra Matriz Leve.

Quando a matriz externa usa vão entre conjuntos, o posicionamento pode acompanhar alterações de tamanho da matriz interna, mantendo o vão configurado.

---

### Matriz de Furação

Replica uma operação de furação em X/Y sem duplicar o Sketch original.

**Origem suportada**

Use uma operação `Hole` ou `Pocket` que represente o primeiro furo/corte.

**Como usar**

1. crie normalmente o primeiro Hole ou Pocket a partir de um único Sketch;
2. deixe essa operação como recurso atual do Body;
3. selecione o Hole/Pocket;
4. execute **Matriz de Furação**;
5. informe quantidade e espaçamento em X e Y;
6. confirme.

**Parâmetros**

- quantidade em X;
- espaçamento em X;
- quantidade em Y;
- espaçamento em Y;
- opção de centralizar a matriz em torno do primeiro furo.

Valores negativos de espaçamento invertem o sentido do eixo correspondente.

**Comportamento**

- recupera o volume removido pela operação de origem;
- cria os cortadores repetidos;
- executa um corte booleano conjunto;
- não duplica o Sketch original;
- mantém a operação original;
- cria um `PartDesign::Feature` dentro do mesmo Body.

Para editar uma matriz já criada, selecione a própria matriz e execute a ferramenta novamente. Se a operação de origem for selecionada e já houver uma matriz associada, a ferramenta pode abrir diretamente o modo de edição.

---

### Mover na Árvore

Reorganiza objetos entre contêineres da árvore do FreeCAD sem mudar sua posição e orientação global.

Esta ferramenta não é o comando de movimentação 3D.

**Um objeto selecionado**

- remove o objeto do contêiner atual;
- devolve o objeto para a raiz do documento;
- preserva o Placement global.

**Duas ou mais seleções**

1. selecione um ou vários objetos que serão movidos;
2. selecione por último o contêiner de destino.

Todos os objetos anteriores à última seleção são movidos para o mesmo destino. A posição e a orientação global de cada objeto são restauradas após a troca de referencial.

Com apenas duas seleções, o comportamento permanece igual: primeiro o objeto, depois o destino.

**Proteções**

- impede hierarquias circulares;
- verifica se o destino aceita objetos;
- não move genericamente uma feature interna de `PartDesign::Body`;
- não insere genericamente objetos dentro de um Body quando isso pode alterar Tip, Origin ou dependências internas;
- valida a diferença de posição e rotação depois da operação.

---

## Regras de seleção e posição

A Direct diferencia a geometria clicada do objeto estrutural que deve ser alterado.

Em operações que movimentam uma peça, uma face de um Pad pode servir como referência geométrica, mas o objeto efetivamente movido pode ser o Body inteiro.

As ferramentas que trabalham com posição global usam a geometria transformada pelo FreeCAD e evitam reaplicar Placement de forma manual quando isso causaria deslocamento duplicado em estruturas com `App::Part`, `PartDesign::Body` ou `App::Link`.

## Alterações da versão 0.9.12

- **Extrudar Face** substitui o antigo fluxo Criar Body na Face.
- Faces pertencentes a um `PartDesign::Body` reutilizam o Body existente.
- Faces de objetos fora de Body passam por conversão automática para Body antes da extrusão.
- O objeto de origem fora de Body só é removido após a conversão concluída.
- O perfil completo da face é copiado para um Sketch independente e o Pad é aberto para configuração.
- **Desenhar na Face** permanece como fluxo separado para criação de uma nova peça independente.
- O contorno da face de referência entra no Sketch como geometria de construção, sem External Geometry entre Bodies.
- Durante a edição do Sketch, sólidos à frente do plano podem ser ocultados temporariamente e são restaurados ao sair.
- A antiga janela de gerenciamento da Linha Guia permanece removida; a ferramenta opera diretamente pela seleção e pelo cursor.
- Mantidas as correções do Snap Cruzamento de Guias, leitura global das guias e integração com Mover por Pontos.

## Compatibilidade

A interface pública da bancada usa o nome **Direct**.

Alguns nomes de propriedades, comandos e módulos internos anteriores são mantidos para preservar compatibilidade com documentos já criados. Esses identificadores não alteram o nome exibido da bancada.

A versão 0.9.12 foi desenvolvida para FreeCAD 1.1+.

## Licença

LGPL-2.1-or-later. Consulte o arquivo `LICENSE`.
