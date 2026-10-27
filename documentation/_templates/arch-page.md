# <Nome do Subsistema> — arquitetura

> Público: dev/auditor/integrador. Página transversal: cobre um concern de sistema (auth, RLS, modelo de dados, API). Atualizar aqui, não repetir nos docs de feature.

## O que é

[Uma a três frases: o que este subsistema faz, qual problema resolve, onde vive no código.]

## Como funciona

[Descrição técnica com referências a arquivos e linhas (`arquivo:linha`). Fluxo principal passo a passo. Diagramas opcionais em texto (mermaid ou ASCII). Não copiar SQL/código inteiro — citar o arquivo.]

## Como estender

[O que mudar para adicionar um novo caso de uso a este subsistema. Ex.: "para novo tipo de actor, adicione o valor ao enum em `arquivo:linha` e atualize a policy em `supabase/migrations/NNNN_*.sql`."]

## Como debugar quando quebra

[Sintomas conhecidos → onde olhar → o que verificar. Ex.: "RLS nega (PostgREST 401) → checar helper `is_org_member` em `arquivo:linha` e policy da tabela". Comandos úteis.]
