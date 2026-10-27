# Central de Ajuda — índice (pt-BR)

Documentação de uso do produto para o usuário final. Diferente de `documentation/`, que é a referência técnica para devs. Aqui é a camada "present": escrita no idioma e na voz do produto.

## Rota e i18n

A rota é `/help` em **todos os locales** — o caminho não muda, só o conteúdo. O catálogo padrão é `pt-BR`; novos idiomas entram como pastas irmãs (`help/en-US/`, etc.) sem mexer no código.

```
help/
  pt-BR/        <- catálogo padrão (dia 1)
    README.md   <- este índice + mapa tela -> artigo
    ...         <- um arquivo por tela/recurso, escrito na fase que o entrega
```

## Como escrevemos

- Voz direta, sem hype, sem emoji.
- Datas no formato DD/MM/AA.
- Cada artigo explica o que a tela/botão/painel faz e para onde navega.
- Um artigo por tela ou recurso; artigos longos usam subtítulos `### Quando X`.

## Cadência

A Central de Ajuda é escrita por fase, junto com as telas — não depois. Uma fase só fecha com a documentação de usuário produzida (Definition of Done).

## Fonte única e mapa tela -> artigo

O artigo Markdown desta pasta é a **fonte da verdade** de toda a ajuda do produto. A ajuda contextual na tela mostra apenas um **snippet curto** que aponta para o artigo canônico; o texto do snippet vive no catálogo i18n (`messages/<locale>/*.json`) e não substitui o artigo. Isso mantém a camada de tela e a camada de artigo alinhadas: o wiring da tela é uma consulta, não uma reescrita.

| Tela (rota) | Artigo canônico | Namespace i18n |
|-------------|-----------------|----------------|
| Uso da ferramenta inteira (Terminal e Claude Code; inclui a página `http://127.0.0.1:8765/`) | [guia-de-uso.md](guia-de-uso.md) | sem i18n (ferramenta de linha de comando) |

> Adicionar uma linha a esta tabela é parte do close-out de cada feature que entrega tela com ajuda. O artigo canônico é a fonte; o snippet i18n aponta para ele.
