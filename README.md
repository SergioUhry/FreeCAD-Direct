# Direct

Workbench para FreeCAD voltada a modelagem direta, posicionamento, linhas guia, medição e matrizes.

**Versão:** 0.9.0  
**FreeCAD:** 1.1+

## Ferramentas

- Criar Body na Face
- Desenhar na Face
- Converter para Body
- Mover por Pontos
- Manipulador
- Posicionar Peça
- Linha Guia
- Snap Cruzamento de Guias
- Peça pelas Guias
- Medidor XYZ Pro
- Matriz Leve
- Matriz de Furação
- Mover na Árvore

## Linha Guia

A Linha Guia permite criar referências e medir diretamente no modelo.

- medida ao vivo junto ao cursor;
- entrada numérica direta;
- travas globais `X`, `Y` e `Z`;
- snap em arestas;
- snap em cruzamentos de Linhas Guia;
- medição sem criar objeto até a confirmação;
- clique esquerdo confirma a guia;
- `Enter` confirma o valor digitado;
- `Esc` cancela.

## Instalação manual

Copie a pasta `Direct` para o diretório de módulos do usuário do FreeCAD e reinicie o programa.

No Linux, o diretório normalmente é:

```text
~/.local/share/FreeCAD/Mod/
```

## Compatibilidade

Alguns identificadores internos antigos são mantidos para preservar compatibilidade com documentos criados por versões anteriores. A interface pública da bancada usa o nome `Direct`.

## Licença

LGPL-2.1-or-later. Consulte o arquivo `LICENSE`.
