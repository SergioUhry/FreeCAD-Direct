# Direct

Workbench para FreeCAD voltada a modelagem direta, posicionamento, linhas guia, medição e matrizes.

**Versão:** 0.9.8  
**FreeCAD:** 1.1+

## Conteúdo

- [Instalação](#instalação)
- [Ferramentas](#ferramentas)
  - [Criar Body na Face](#criar-body-na-face)
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

### Criar Body na Face

Cria uma nova peça Part Design a partir de uma face plana existente.

**Como usar**

1. Selecione exatamente uma face plana.
2. Execute **Criar Body na Face**.
3. Informe o nome da nova peça.
4. O FreeCAD cria um novo `PartDesign::Body` e um `Sketch` e abre o Sketcher.

**Comportamento**

- o novo Body é independente da geometria de origem;
- o plano XY local é orientado pela face selecionada;
- a origem local é posicionada no canto inferior esquerdo da face;
- a orientação da vista atual é usada para definir X e Y locais de forma previsível;
- se a face estiver dentro de um `App::Part`, o novo Body é inserido nesse Part preservando a posição global.

**Uso típico**

Criar rapidamente uma nova peça apoiada visualmente em outra peça sem criar vínculo topológico entre elas.

---

### Desenhar na Face

Cria um Sketch independente orientado por uma face existente.

**Como usar**

1. Selecione exatamente uma face.
2. Execute **Desenhar na Face**.
3. O Sketch é criado e aberto automaticamente para edição.

**Comportamento**

- se a face pertence a um Body, o Sketch é criado dentro desse Body;
- o Sketch usa `MapMode = Deactivated`;
- a posição é calculada a partir da face, mas não fica mapeada a ela;
- a origem do Sketch é colocada no canto inferior esquerdo local da face;
- a ferramenta evita dependência topológica direta da face selecionada.

**Diferença para Criar Body na Face**

- **Criar Body na Face** inicia uma nova peça;
- **Desenhar na Face** adiciona um Sketch ao contexto da peça existente.

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

#### Linha Guia → plano de uma face

Selecione uma ou várias Linhas Guia e, por último, uma face plana de destino.

- as guias são projetadas para o plano pela direção da vista atual;
- em vista ortográfica, o centro da guia permanece no mesmo ponto visual da tela;
- a guia precisa ser paralela ao plano da face;
- a geometria global é resolvida sem reaplicar `Placement`;
- várias guias podem ser posicionadas na mesma operação.

**Objetos móveis**

- features de Part Design movem o Body correspondente;
- `App::Link` move o próprio Link;
- a posição global é convertida corretamente para o sistema local do `App::Part` pai quando necessário.

---

### Linha Guia

Cria referências geométricas e também funciona como ferramenta de medição rápida no 3D.

Existem dois modos de uso.

#### Modo direto no 3D

Selecione uma aresta reta ou uma Linha Guia e execute **Linha Guia**.

A linha fantasma acompanha o cursor e a medida aparece junto ao ponteiro.

**Controles**

| Ação | Resultado |
|---|---|
| mover o mouse | pré-visualiza a posição e atualiza a medida |
| `X`, `Y` ou `Z` | trava o deslocamento/plano global correspondente |
| digitar um valor | informa a distância numericamente |
| `Enter` | confirma o valor informado |
| clique esquerdo | confirma a guia na posição atual |
| `Esc` | cancela |
| clique direito | cancela |

**Medição e snap**

- a medida é exibida ao vivo junto ao cursor;
- passar sobre uma aresta permite ler a distância sem criar objeto;
- a guia só é criada após confirmação;
- há captura de arestas no plano ativo;
- há captura de cruzamentos reais entre Linhas Guia;
- as travas X/Y/Z permitem medições em referências globais;
- o preview é visual e não altera a geometria do documento durante o movimento do mouse.

A caixa de medida também indica o contexto capturado, como eixo/plano e tipo de referência quando disponível.

#### Janela avançada

Se a ferramenta for executada sem uma única aresta reta selecionada, é aberta a janela **Linhas Guia**.

Modos disponíveis:

- paralela à aresta selecionada;
- guia X/Y/Z pelo vértice;
- três guias X/Y/Z pelo vértice;
- central entre duas arestas paralelas.

A janela também permite:

- definir comprimento automático ou manual;
- atualizar todas as guias;
- mostrar ou ocultar todas as guias;
- apagar todas as guias;
- criar ou abrir Sketcher em uma guia selecionada;
- escolher plano XY, XZ, YZ ou perpendicular à guia para o Sketch;
- opcionalmente vincular a guia como geometria externa do Sketch.

---

### Snap Cruzamento de Guias

O Snap Direct inicia **desligado**. Quando ativado, ele funciona em modo exclusivo: desliga temporariamente os snaps nativos e captura somente cruzamentos reais entre Linhas Guia. Durante **Mover por Pontos**, o cruzamento é entregue diretamente ao ponto consumido pelo comando Draft. Ao desligar o Snap Direct, o estado anterior dos snaps nativos é restaurado.


Ativa um snap dedicado aos cruzamentos geométricos reais entre Linhas Guia.

**Como usar**

1. selecione primeiro a referência da peça que será posicionada;
2. ative **Snap Cruzamento de Guias**;
3. aproxime o cursor de um cruzamento de guias;
4. clique no cruzamento desejado;
5. use **Posicionar Peça** para completar o posicionamento.

**Comportamento**

- somente cruzamentos 3D válidos são considerados;
- cruzamentos apenas aparentes na tela, sem interseção geométrica real, são ignorados;
- enquanto o Snap Direct está ativo, os snaps nativos Draft/BIM são temporariamente desativados e bloqueados;
- ao desligar o Snap Direct, o estado anterior dos snaps nativos é restaurado;
- a ferramenta usa um ponto temporário de seleção para entregar o cruzamento às demais ferramentas;
- o botão é do tipo liga/desliga.

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

## Compatibilidade

A interface pública da bancada usa o nome **Direct**.

Alguns nomes de propriedades, comandos e módulos internos anteriores são mantidos para preservar compatibilidade com documentos já criados. Esses identificadores não alteram o nome exibido da bancada.

A versão 0.9.2 foi desenvolvida para FreeCAD 1.1+.

## Licença

LGPL-2.1-or-later. Consulte o arquivo `LICENSE`.
