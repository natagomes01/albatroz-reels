# Guia de uso: da aula gravada aos Shorts

> Locale: pt-BR | Atualizado: 30/09/26 | Vale para o `main` depois do S6

## O que esta ferramenta faz

Pega uma aula longa gravada no iPhone e devolve Shorts verticais 1080x1920, com legenda queimada, corte de silêncio, câmera que segue você e cor e som acertados. Tudo roda no Mac. A única etapa que usa a internet é a análise, que chama o Claude pelo seu plano Max.

Cada etapa abaixo tem dois caminhos, e os dois fazem a mesma coisa:

- **No Claude Code:** você escreve um pedido em português e a sessão roda o comando, lê o resultado e explica.
- **No Terminal:** você mesmo cola o comando.

O Claude Code é melhor quando algo pode dar errado ou quando você quer entender o que aconteceu. O Terminal é mais rápido quando você já sabe o que quer.

## Antes de tudo (uma vez por Mac)

1. Abra o Terminal e entre na pasta do projeto:

   ```
   cd ~/dev/albatroz-shorts
   ```

2. Instale as dependências e confira o ambiente:

   ```
   uv sync
   uv run shorts doctor
   ```

   Toda linha deve sair `[ok  ]`. Um `[FAIL]` diz o que falta (ffmpeg-full, whisper, transcreve, espaço em disco). O `doctor` não confere se o `claude` está logado: rode `claude` uma vez e faça login com o plano Max.

3. Para abrir o Claude Code nesta pasta:

   ```
   cd ~/dev/albatroz-shorts && claude
   ```

**No Claude Code, peça:** "Roda o `shorts doctor` e me diz se falta alguma coisa no Mac."

## As etapas, em ordem

Nos exemplos, a aula se chama `260927-catequese-permanente-1`. Troque pelo nome da sua.

### 1. Pôr a gravação no lugar

Os vídeos ficam fora do Git, em `~/dev/albatroz-media/masters/`. Copie o `.mov` original do iPhone para lá (o arquivo da câmera, nunca um exportado menor). A ferramenta nunca copia vídeo por conta própria: se o arquivo estiver em outro disco, ela pede para você mover.

Antes de uma aula longa, confira o espaço livre. Uma aula de 100 minutos em 4K ocupa uns 6 GB, e o `doctor` avisa abaixo de 10 GB.

### 2. Criar o job e transcrever (`ingest`)

Cria a pasta da aula em `jobs/` e transcreve cada palavra com o tempo dela. Roda no Mac, sem custo de LLM. Em aula longa, demora.

**No Claude Code:** "Cria o job da aula `~/dev/albatroz-media/masters/260927-catequese-permanente-1.mov` no canal catholic-br, formato solo-standing, tema 'Salmo 22 na Septuaginta'."

**No Terminal:**

```
uv run shorts ingest ~/dev/albatroz-media/masters/260927-catequese-permanente-1.mov --channel catholic-br --format solo-standing --topic "Salmo 22 na Septuaginta"
```

- `--channel`: `catholic-br`, `ai-en` ou `ai-br` (lista em `channels.toml`).
- `--format`: `solo-standing` (em pé) ou `solo-seated` (sentado).
- `--topic`: uma linha sobre a aula. Ajuda a corrigir nomes e termos em hebraico, grego e latim nas legendas.

Se a transcrição falhar no meio, rode o mesmo comando de novo: ele continua de onde parou.

### 3. Achar os melhores trechos (`analyze`)

Três passadas do Claude: uma varre a aula em janelas de 2 minutos, outra detalha as melhores, a terceira revisa os candidatos. No fim, corrige palavras mal ouvidas nas legendas. Essa é a etapa que tem custo. A amostra de 10 minutos custou US$ 0,81 em preço de lista de API, mas no plano Max isso sai do limite de uso, sem cobrança extra.

**No Claude Code:** "Roda o `analyze` do job 260927-catequese-permanente-1 e me diz quantos candidatos saíram e quanto custou."

**No Terminal:**

```
uv run shorts analyze 260927-catequese-permanente-1
```

- Se mais de 40 janelas passarem do corte, ele pergunta se manda todas para a passada detalhada. `N` fica com as 40 melhores.
- Se o limite do plano acabar, as chamadas já feitas ficam guardadas. Rode de novo quando o limite voltar.
- Depois que você já aprovou ou rejeitou clips, o `analyze` se recusa a rodar, para não trocar a lista por baixo das suas decisões. Para recomeçar do zero, use `--force` (a revisão antiga fica arquivada).

### 4. Revisar na página (`review`)

Abre a página de revisão no navegador. É aqui que você decide o que vira Short.

**No Claude Code:** "Abre a página de revisão do job 260927-catequese-permanente-1."

**No Terminal:**

```
uv run shorts review 260927-catequese-permanente-1
```

A página abre em `http://127.0.0.1:8765/`. O servidor fica rodando até você apertar Ctrl+C no Terminal, então use uma segunda janela do Terminal para os outros comandos. Fechar a aba do navegador não para o servidor.

Na página:

- **Assistir:** `▶ PLAY` toca só os trechos do clip.
- **Decidir:** `APPROVE` (barra verde-oliva, `APPROVED`) ou `REJECT` (barra cor de tijolo, `REJECTED`, texto cinza). Cada clique salva na hora.
- **Ajustar o corte:** clique numa palavra para começar ali; Shift+clique para terminar ali. Os botões `START −0.5`, `START +0.5`, `END −0.5`, `END +0.5`, `START ◀ SENTENCE` e `END ▶ SENTENCE` fazem ajustes finos. A primeira e a última palavra de cada trecho têm um contorno laranja.
- **Corrigir uma palavra da legenda:** Option (⌥)+clique no Mac, Alt+clique no Windows. Deixe a caixa vazia para remover a palavra: ela fica na tela riscada, com ⌫, e um clique traz de volta.
- **Sugestão ou minha:** quando você corrige uma palavra que o Claude já tinha corrigido, aparecem as duas versões lado a lado (`SUGGESTION` e `MINE`). A que tem a caixa cheia é a que vai para o vídeo. Clique na outra para trocar.
- **Desfazer e refazer:** Command (⌘)+Z e Shift+Command (⌘)+Z no Mac; Ctrl+Z e Ctrl+Y (ou Ctrl+Shift+Z) no Windows. Também há os botões `UNDO` e `REDO` em cada card. As teclas agem no último clip que você mudou, o que tem o `UNDO` com borda laranja. O histórico some quando o servidor para; o `review.json` guarda o estado final.
- **Título e gancho:** as duas caixas de texto do card. Título com até 60 caracteres.
- **Força do áudio (dereverb):** no topo da página, o painel de áudio toca um trecho de 20 s em quatro forças (`off`, 10, 20, 30). Ouça, escolha com `Choose` e o painel vira `Audio: dereverb 20 · change`. Cada aula tem a sua sala, então a escolha vale para a aula toda. Enquanto você não escolher, os botões de render ficam desligados. Num clip específico, o seletor `Audio` da gaveta troca a força só dele. Preparar o trecho leva cerca de 1 minuto na primeira vez.
- **Tema:** `LIGHT`, `DARK` ou `SYSTEM` no canto do cabeçalho. `SYSTEM` segue o modo do Mac. A escolha fica neste navegador.

### 5. Renderizar (`render`)

Faz os vídeos de todos os clips aprovados, um por vez: segue você com a câmera virtual, corta os silêncios, põe legenda, acerta cor e som. Roda no Mac, sem custo de LLM. Um clip que falha não para os outros.

**No Claude Code:** "Renderiza os clips aprovados do job 260927-catequese-permanente-1 e me diz onde ficaram."

**No Terminal:**

```
uv run shorts render 260927-catequese-permanente-1
```

Os Shorts ficam em `~/dev/albatroz-media/renders/catholic-br/260927-catequese-permanente-1/`, um `.mp4` por clip com um `.json` ao lado. Clip que não mudou desde o último render é pulado (`skipped (fresh)`). Mudou algo na página? Rode o `render` de novo e só os clips alterados são refeitos.

O `render` já faz o rastreamento e as legendas sozinho. Os dois comandos abaixo servem para conferir uma etapa antes:

- `uv run shorts track 260927-catequese-permanente-1 --preview`: gera um vídeo de prévia por clip com o retângulo que a câmera vai mostrar.
- `uv run shorts captions 260927-catequese-permanente-1`: gera só o arquivo de legenda.

### 6. Conferir a zona segura (opcional)

Põe por cima do vídeo o gabarito laranja das áreas que o Instagram e o YouTube cobrem, para ver se a legenda fica livre.

**No Terminal:**

```
uv run shorts render 260927-catequese-permanente-1 --safe-zone
```

Atenção: essa versão sobrescreve o arquivo final. Depois de olhar, rode o `render` sem `--safe-zone` para voltar ao vídeo limpo.

### 7. Limpar os rejeitados e fazer backup

**Apagar os vídeos de clips que você rejeitou depois de renderizar:**

```
uv run shorts clean 260927-catequese-permanente-1
```

Só apaga renders de clips rejeitados. Aprovados, pendentes e a gravação original ficam.

**Copiar para o Google Drive** (precisa do `rclone` configurado uma vez, ver `docs/runbooks/drive-backup.md`):

```
uv run shorts backup 260927-catequese-permanente-1 --dry-run
uv run shorts backup 260927-catequese-permanente-1
```

O `--dry-run` mostra o que iria sem mandar. O backup só copia, nunca apaga nada no Drive.

## Atalhos e comandos de apoio

**"Faz o próximo passo":** `run` olha o estado do job e faz o que falta (analisar, ou renderizar o que foi aprovado). Nunca faz o `ingest`.

```
uv run shorts run 260927-catequese-permanente-1
```

**Quanto custou:** mostra o gasto de LLM por passada, por rodada e por minuto de aula, e projeta o custo de uma aula de N minutos.

```
uv run shorts cost 260927-catequese-permanente-1
uv run shorts cost 260927-catequese-permanente-1 --project 100
uv run shorts cost --all
```

**Refazer só as correções de legenda** (por exemplo, depois de mudar o tema da aula):

```
uv run shorts fixwords 260927-catequese-permanente-1 --topic "Salmo 22 na Septuaginta"
```

**Um Short manual, com início e fim que você escolhe** (sem análise e sem página). Precisa do arquivo de palavras ao lado do vídeo (`<vídeo>.palavras.json`), gerado com `/usr/bin/python3 ~/dev/transcreve/transcreve.py <vídeo> --palavras --idioma pt` (a função `trs` do zsh ainda aponta para uma cópia antiga, sem `--palavras`):

```
uv run shorts clip ~/dev/albatroz-media/samples/amostra-10min.mov --channel catholic-br --format solo-standing --from 1:18.9 --to 1:41.2
```

Sai em `~/dev/albatroz-media/renders/catholic-br/manual/`.

**No Claude Code, para qualquer um deles:** descreva o que quer ("me mostra quanto custou a aula de ontem", "faz um Short manual de 1:18 a 1:41 da amostra") e a sessão escolhe o comando.

## Prompt pronto para uma aula inteira no Claude Code

Cole isto numa sessão nova, aberta com `cd ~/dev/albatroz-shorts && claude`, trocando o arquivo e o tema:

```
Read CLAUDE.md and documentation/features/shorts-cli.md. We are processing a new class from start to finish: ~/dev/albatroz-media/masters/<file>.mov, channel catholic-br, format solo-standing, topic "<one line about the class>". Run `shorts doctor`, then `ingest`, then `analyze`, and tell me the number of candidates and the cost line. Then start `shorts review` and wait while I approve and fix clips on the page. When I say so, run `render`, tell me where the Shorts are, and show `shorts cost` for the job. Stop and ask before any `--force`, any `clean` or any `backup`.
```

## Onde fica cada coisa

| O quê | Onde |
|------|------|
| Gravações originais | `~/dev/albatroz-media/masters/` |
| Shorts prontos | `~/dev/albatroz-media/renders/<canal>/<job>/` |
| Shorts manuais | `~/dev/albatroz-media/renders/<canal>/manual/` |
| Arquivos de trabalho de cada aula | `~/dev/albatroz-shorts/jobs/<job>/` |
| Suas decisões na página | `jobs/<job>/review.json` (o único arquivo do job que vai para o Git) |
| Página de revisão | `http://127.0.0.1:8765/`, enquanto o `shorts review` roda |
| Referência completa de cada comando | `documentation/features/shorts-cli.md` |
| Roteiro passo a passo da primeira rodada | `documentation/runbooks/live-run-sample.md` |

## Dúvidas comuns

**A página diz que a porta 8765 está ocupada.**
Já existe um `shorts review` rodando em outra janela. Pare com Ctrl+C, ou abra outro com `--port 8766` e acesse `http://127.0.0.1:8766/`.

**O vídeo não toca no navegador.**
Os `.mov` do iPhone vêm em HEVC. Teste no Safari, que toca esse formato.

**O render parou com `UVR failed` ou `choose the audio strength`.**
`choose the audio strength` quer dizer que falta escolher a força no painel de áudio da página. `UVR failed` é o programa de áudio que travou: rode o `render` de novo (ele tenta até 3 vezes sozinho, e o que já ficou pronto fica guardado). Se repetir, rode `uv run shorts doctor`.

**Mudei um clip na página depois de renderizar. Preciso refazer tudo?**
Não. Rode `render` de novo: só os clips que mudaram são refeitos.

**O `analyze` parou no meio por limite do plano.**
Nada se perde. As chamadas feitas ficam guardadas; rode o mesmo comando quando o limite voltar.

**Uma legenda saiu com palavra errada.**
Corrija na página com Option (⌥)+clique (Alt+clique no Windows) e rode `render` de novo.

**Quero recomeçar a análise do zero.**
`uv run shorts analyze <job> --force`. Suas decisões atuais ficam arquivadas como `review.<data>.json` dentro da pasta do job.
