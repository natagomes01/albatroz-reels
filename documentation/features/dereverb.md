# Dereverb (audio strength) — referência técnica

> Fase: S8 (parte de áudio) | Branch: `s8-dereverb` (PR #1, mergeada em 02/10/2026) | Testes: `tests/test_dereverb*.py`, `tests/test_excerpt.py`, `tests/test_review_audio.py`, `tests/test_render_audio_inputs.py` | Lição: `_think/lessons/04-dereverb-forca-do-audio.md`
> Público: dev/auditor. Estilo: referência. Conceitos em `_think/lessons/_conceitos.md`. Spec: `docs/superpowers/specs/2026-10-01-dereverb-strength-design.md`.

## Escopo

Remove o reverb da sala da voz com o modelo UVR-DeEcho-DeReverb, numa força escolhida de ouvido por aula (e por clip, se preciso). A força entra na chave de render e libera ou bloqueia o render.

## Dados

- **`review.json["dereverb"]`**: força da aula, um valor de `[dereverb] levels` (`config.toml`). Ausente = não escolhida.
- **`decisions[id]["dereverb"]`**: override do clip; `null` volta a seguir a aula. É uma edição como as outras (`review/state.py` `apply_edit`, com undo e redo).
- **Força efetiva**: override, senão a da aula (`dereverb.py:64`). Canal com `sound = false` não usa dereverb e a força não entra na chave.
- **Cache**: `<media_root>/cache/<job>/audio/`, um WAV por (master, janela, força, modelo) (`dereverb.py:96`), mais `excerpt-<nível>.m4a`. Pode apagar; é refeito sob demanda.

## Regras e invariantes

- **Gate**: canal com som, master com áudio e força não escolhida: a página desliga os botões, `POST /api/render*` responde 409 e `shorts render` sai com 1 e `choose the audio strength on the review page first` (`dereverb.py:17,70`, `stages.py`). O gate só roda se há clip aprovado.
- **Janela**: corte do master com 1 s de folga de cada lado (`PAD`, `dereverb.py:76`), UVR, corte de volta ao tamanho da janela, `os.replace` atômico.
- **Checagem de tamanho**: a saída do UVR é comparada com o áudio realmente extraído (tolerância 50 ms), não com a duração nominal. O áudio do `.mov` é cerca de 150 ms mais curto que o container, e perto do fim do master a janela volta mais curta (`dereverb.py:153`).
- **Retry**: `run_separator` (`dereverb.py:102`) tenta até 3 vezes só em saída -6, -11 ou texto `recursive_mutex` / `Separation complete`; esvazia a pasta entre tentativas e nunca aceita saída de execução com erro. Outro erro falha na hora.
- **Render**: os WAVs entram por `audio_inputs` (`audio.py:46`) e `RenderInputs.audio_files`; `_concat_graph` (`audio.py:60`) é compartilhado por `loudnorm_measure` e `render_audio`.
- **Memória**: UVR roda como processo filho e termina antes do render de vídeo. Pico medido de cerca de 3,3 GB com o modelo.
- **Exclusão**: a página responde 409 se o excerpt e um render se sobrepõem (`review/audio.py`, `RenderQueue.busy()`).

## Superfície

- `shorts excerpt <job>` faz os quatro `.m4a` (primeiros 20 s do primeiro candidato, com dereverb, `CLEANUP` e `loudnorm` em duas passadas); `analyze` chama isso ao final (`excerpt.py:45`).
- `shorts clip ... --dereverb N` (N em `levels`; recusado em canal sem som).
- Rotas: `GET /api/audio`, `POST /api/audio`, `POST /api/audio/prepare`, `GET /media/excerpt/<nível>.m4a` (`review/server.py`).
- `shorts doctor`: checagens `UVR (audio-separator)` e `UVR model`.

## Como debugar

| Sintoma | Onde olhar |
|---|---|
| `UVR failed (exit N)` | Rode de novo (retry automático em -6/-11). Se repetir, `shorts doctor` e o runbook `new-machine-setup.md`, seção Dereverb (UVR). |
| `UVR output is X s for a Y s input` | Janela perto do fim do master; confira `audio_duration` e o corte em `_dereverb_window`. |
| Botões de render desligados | Força da aula não escolhida (`review.json["dereverb"]`). |
| Excerpt velho depois de `analyze --force` | O `.m4a` não está ligado ao candidato nem ao modelo; apague `cache/<job>/audio/excerpt-*.m4a`. |
| Dois UVR juntos, Mac lento | Não há trava entre processos; espere um terminar. |

## Testes

`fake_uvr` em `tests/conftest.py` (modos de falha `FAKE_UVR_*`) cobre tudo sem o modelo. `tests/test_dereverb_real.py` roda UVR de verdade e pula sem o programa ou o modelo. Medida de um clip de 30 s na força 20: 22,2 s e 753 MB com UVR; 10,5 s e 354 MB do cache (`_think/sdd-runs/2026-10-01-S8/MEASUREMENT.md`).

## Decisões-chave

ADR `documentation/decisions/0004-dereverb-uvr-external-program.md`; lição `_think/lessons/04-dereverb-forca-do-audio.md`.

## Depende de / desbloqueia

Depende de S7 (fila de render, gaveta por clip) e S5 (undo). Pendente no backlog (`_think/roadmap.md`): timeout do UVR, trava entre processos, excerpt ligado ao candidato e ao modelo.
