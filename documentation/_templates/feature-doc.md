# <Wave/Feature> — referência técnica

> Fase: <P0 · WN> | Branch: `<p0/wN-...>` | Migrations: `<arquivos>` | Testes: `<arquivos>` | Lição correspondente: `_think/lessons/<NN-...>.md`
> Público: dev/auditor/integrador. Estilo: **referência** (lookup), não narrativa. Linkar conceitos para `_think/lessons/_conceitos.md`.

## Escopo — o que esta fase entrega

[1–3 frases: o que existe no banco/código depois desta fase que não existia antes.]

## Modelo de dados

Para cada tabela criada/alterada:

### `nome_da_tabela`
- **Propósito:** [uma linha].
- **Colunas-chave:** `coluna tipo` — significado; FKs e `on delete`; defaults relevantes.
- **Índices:** [quais e por quê].
- **Enums usados:** [quais].

(Repetir por tabela. Enums novos: nome + valores. Não copiar o SQL inteiro — referenciar o arquivo de migration em `arquivo:linha`.)

## Regras e invariantes (o que o banco garante sozinho)

- **RLS:** quais policies, e o padrão (`is_org_member(org) OR is_platform_admin()`); o que cada papel pode.
- **Triggers:** nome → o que faz → quando dispara.
- **Constraints:** UNIQUE/CHECK que impõem regra de negócio (ex.: dedup, idempotência).

## Pontos de extensão / ganchos

[Colunas/enums "porta aberta" deixados para o futuro, e onde o próximo subsistema pluga.]

## Como debugar / onde olhar quando quebra

[Sintomas prováveis → arquivo/função/tabela a inspecionar. Ex.: "erro de RLS (PostgREST 401/empty) → conferir policy X e helper Y". Comandos úteis (`supabase test db`, query de verificação).]

## Testes

[Quais suites pgTAP/Vitest cobrem isto e o que asseguram. Como rodar.]

## Decisões-chave

[Só o ponteiro: ver ADR em `documentation/decisions/NNNN-*.md` e a lição `_think/lessons/<NN-...>.md` §"Decisões e alternativas". Não repetir o raciocínio aqui.]

## Dependências e o que vem depois

[Do que esta fase depende; o que ela desbloqueia; qual subsistema futuro constrói a UI em cima.]
