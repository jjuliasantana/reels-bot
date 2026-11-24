# Reels Bot — canal dark de games (Instagram)

Bot autônomo: monitora o YouTube → agrupa tendências em qualquer idioma → escolhe uma pauta com ângulo
original → gera roteiro, narração, legendas e ilustrações **originais** com IA → exporta MP4 9:16 (30–45 s) →
publica no Instagram (só depois da sua autorização). Relatórios e avisos em pt-BR; conteúdo do Reel em en-US.

Nada de terceiros é baixado ou reutilizado: vídeos de outros criadores servem apenas como sinal de tendência
(título, canal, idioma, contagem de views). As cenas recebem o selo "ILLUSTRATION — not gameplay or official footage".

## Rodar localmente
```bash
pip install -r requirements.txt          # precisa também de ffmpeg no PATH
cp .env.example .env                     # preencha o que tiver; o que faltar vira dado simulado/placeholder
set -a; source .env; set +a
python -m bot.main run --dry-run --sim   # teste completo com dados simulados (não publica)
python -m bot.main collect               # 1ª coleta real (YouTube)  — repita ~4 h depois
python -m bot.main run --dry-run         # pauta real + MP4, sem publicar
```
Saída: `output/relatorio_<pauta>-<data>.md` (pauta, evidências, custo, etapas executadas) e
`output/<pauta>-<data>/reel_*.mp4`.

## Hospedar na nuvem (GitHub Actions — roda com seu PC desligado)
1. Crie um repositório **público** no GitHub (público porque o Instagram precisa baixar o MP4 de uma URL pública;
   o bot hospeda o vídeo como *release asset*). Se preferir repositório privado, use `hosting: s3` no `config.yaml`
   e configure `S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (e `pip install boto3`).
2. Suba esta pasta. O workflow `.github/workflows/bot.yml` já agenda: coleta a cada 4 h e produção 1x/dia.
3. Em **Settings → Secrets and variables → Actions → Secrets**, adicione o que tiver (veja tabela abaixo).
4. Teste manualmente: **Actions → reels-bot → Run workflow → mode = dry-run**. O MP4 e o relatório ficam nos
   *artifacts* da execução.
5. Para ligar a publicação (depois de autorizar): `config.yaml → publishing.enabled: true` **e** em
   **Settings → Secrets and variables → Actions → Variables** crie `PUBLISH_ENABLED = true`. Os dois são exigidos.

Alternativa: `Dockerfile` incluso — roda em qualquer VPS/Cloud Run/Fly.io com um cron chamando
`python -m bot.main collect` (a cada 4 h) e `python -m bot.main run` (1x/dia).

## Credenciais (onde conseguir / onde configurar)
| Variável | Para quê | Onde obter |
|---|---|---|
| `YOUTUBE_API_KEY` | monitorar tendências | Google Cloud Console → ativar *YouTube Data API v3* → Credenciais → chave de API. Quota grátis 10.000 un/dia (cada busca = 100). |
| `GEMINI_API_KEY` | roteiro, rotulagem dos clusters e embeddings multilíngues — **gratuito** (cota free do Google AI Studio) | aistudio.google.com → *Get API key* (sem cartão). Obs.: na cota gratuita o Google pode usar os prompts para melhorar seus modelos. |
| — (edge-tts) | narração com voz neural e tempos por palavra para as legendas — **gratuito**, sem chave | já incluso em `requirements.txt` (usa o serviço de leitura em voz alta do Microsoft Edge; não é uma API oficial, pode mudar sem aviso). |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | opcionais, pagos: troque `llm_provider` / `tts_provider` / `embeddings` no `config.yaml` se quiser mais qualidade | console.anthropic.com / platform.openai.com |
| `IG_ACCESS_TOKEN` (+ `IG_USER_ID` opcional) | publicar Reels e ler métricas | developers.facebook.com → criar app → caso de uso *Instagram* → **API setup with Instagram login** (não precisa de Página do Facebook) → adicionar as permissões `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_insights` → *Generate access tokens* → adicionar sua conta profissional → gerar token (60 dias; renove). O bot descobre o `IG_USER_ID` sozinho via `/me`. Teste com `python -m bot.main check`. |
| `BUFFER_ACCESS_TOKEN` + `BUFFER_PROFILE_ID` | alternativa ao Graph API (`publishing.provider: buffer`) | painel do Buffer (acesso à API depende do seu plano). |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` ou `ALERT_WEBHOOK_URL` | avisos de erro/sucesso | @BotFather no Telegram / webhook do Discord ou Slack |
| `GITHUB_TOKEN` | hospedar o MP4 (automático no Actions) | — |

Sem alguma credencial o bot **não para**: usa dados simulados (identificados como `SIM…`), roteiro-modelo e
áudio placeholder, e lista no relatório o que foi real e o que não foi.

## YouTube Shorts e TikTok
As APIs de upload do YouTube e do TikTok deixam o vídeo **privado** até o projeto passar por auditoria da
plataforma. Até lá, use `publishing.provider: telegram`: o bot gera o Reel e envia o MP4 no Telegram com título e
legenda prontos para cada plataforma; você posta pelo celular. Pedido de auditoria do YouTube: formulário
"YouTube API Services – Audit and Quota Extension" no Google Cloud Console (gratuito).

## Regras de segurança já embutidas
- `publishing.enabled: false` por padrão + `PUBLISH_ENABLED` precisa ser `true` no ambiente.
- Máx. `max_posts_per_day` (1) e limites de gasto `max_usd_per_video / day / month` em `config.yaml`.
- Idempotência: `post_key = pauta + data`; o `creation_id` do Instagram é salvo antes do publish — uma nova
  execução após falha retoma em vez de criar post duplicado. `concurrency` no workflow impede execuções paralelas.
- Pauta parecida nos últimos `cooldown_days_same_topic` dias é pulada. Sinal com 1 coleta é "preliminar" e
  (por padrão) não publica.
- Métricas do próprio perfil (plays, saves, shares) viram um bônus/penalidade por jogo na próxima seleção.

## Custo
**US$ 0,00** na configuração padrão: YouTube Data API (cota grátis), Gemini free tier, edge-tts, ilustrações
procedurais, GitHub Actions em repositório público, Instagram Graph API. Pago só se você trocar para
OpenAI/Anthropic (~US$ 0,03/vídeo) ou ligar `image_generation: openai` (~US$ 0,25/vídeo).

## Limites conhecidos desta versão
- Checagem de fatos: o roteirista é instruído a só afirmar o que fontes oficiais confirmam e a marcar o resto como
  rumor; o relatório lista `claims` com status. Ainda não há consulta automática a sites de notícias.
- Legendas por palavra vêm do edge-tts (ou whisper, se usar OpenAI); sem narração real, os tempos são estimados.
- Gemini free tier tem limite de requisições por minuto/dia; o bot faz ~3 chamadas por execução, bem abaixo disso.
- Buffer: a API clássica pode não estar liberada para contas novas — prefira o Instagram Graph API.
