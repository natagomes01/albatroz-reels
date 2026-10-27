# Comece aqui

O Albatroz Reels transforma vídeo gravado em Reels, Shorts e TikToks verticais, no seu próprio Mac ou PC
com Windows. Quem edita é o Claude Code: você conversa com ele em português e ele roda o pipeline, monta
as animações e confere o resultado.

Foi feito pelo Natã Gomes, da Albatroz Studio, para o canal Católico na Bíblia. O perfil desse canal fica
em `profiles/catholic-br/` como exemplo. Você vai criar o seu ao lado dele.

## O que precisa

- Mac (M1 com 8 GB já basta) ou PC com Windows 10/11.
- [Claude Code](https://claude.com/claude-code) instalado, numa assinatura Claude (Pro ou Max). As
  passadas de IA, que escolhem os melhores trechos e corrigem as legendas, gastam o seu plano.
- Git e uns 20 GB livres. Os vídeos ficam numa pasta fora do repositório e nunca entram no Git.

## Passo a passo

1. **Faça um fork** deste repositório no GitHub (botão *Fork*) e clone o seu fork.
2. **Abra a pasta no Claude Code** e cole:

   > Leia o CLAUDE.md e use a skill setup para instalar isto no meu computador.

   Ele pergunta onde guardar os vídeos e qual e-mail usar nas buscas de imagem, instala ffmpeg,
   whisper e o resto, e só termina quando `shorts doctor` sai todo verde. As permissões já vêm em
   `.claude/settings.json`: ele edita arquivos e roda os comandos do pipeline sem pedir licença a cada
   passo, e fica proibido de apagar pastas inteiras ou forçar push.
3. **Crie o seu canal:**

   > Use a skill new-channel para criar o meu canal.

   Ele entrevista você sobre o público, os termos que você fala muito (para a legenda não errar) e os
   vídeos de referência que você quer seguir, e escreve tudo em `profiles/<seu-canal>/`.
4. **Faça o primeiro Short:**

   > Faz um Short do trecho 1:10 a 1:45 do vídeo `<caminho do vídeo>` no meu canal.

## Os formatos

Cada formato tem uma skill com o passo a passo e os erros que já custaram um render. Os exemplos vêm do
Católico na Bíblia, e cada skill diz o que trocar para o seu canal.

| Formato | Como pedir |
|---|---|
| Corte de aula: o pipeline acha os melhores momentos de um vídeo longo e gera Shorts legendados | "Cria o job da aula `<vídeo>` e roda a análise" (guia completo em `help/pt-BR/guia-de-uso.md`) |
| Citação sem rosto: uma voz lê uma citação sobre pinturas, com zoom lento e legenda | "Faz um Reel sem rosto no formato do Santo Ambrósio com esta citação" |
| Gancho animado: tomadas de celular, gancho com tipografia em movimento, faixa de retenção e cartão final | "Faz no formato do Êxodo 20 com estas duas tomadas" |
| Reação: vídeo de outra pessoa em cima, você reagindo embaixo, depois tela cheia | "Faz uma reação a este link com a minha gravação" |
| Corte longo animado: um trecho de vídeo longo com gancho e corpo montados no Remotion | "Faz no formato da Eleição o trecho 12:30 a 14:10 da aula" |

## Mudar o estilo e dar referências

Diga ao Claude o que quer, com as suas palavras: "legenda maior e no meio da tela", "minhas cores são
#1B3A4B e #F2C14E", "quero um gancho como o deste vídeo: `<link>`". A skill new-channel guarda as
referências em `profiles/<seu-canal>/references.md`, só com o link e o que você gostou em cada uma.
Vídeo de outra pessoa nunca entra no repositório.

Depois de publicar, conte ao Claude o que funcionou e o que não funcionou. Isso vai para
`profiles/<seu-canal>/memory/`, e a análise passa a escolher trechos levando isso em conta.

## Formato novo

Quer um formato que nenhuma skill cobre? Peça um *spike*: um script descartável, amarrado a um único
vídeo, feito para descobrir se o formato funciona. Se o render ficar bom, o Claude escreve uma skill nova
com o passo a passo e as regras aprendidas. Só o formato que você repete muito vira código do pipeline,
com especificação e testes.

## Licença

MIT. Pode usar, mudar e publicar, inclusive comercialmente, mantendo o aviso de copyright do arquivo
`LICENSE`.
