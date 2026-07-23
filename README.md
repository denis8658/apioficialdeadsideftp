# Deadside Data API

Backend FastAPI assíncrono e multi-servidor para importar backups persistentes do Deadside, preservar snapshots e expor personagens, veículos e coordenadas calibradas para Leaflet.

Esta entrega implementa a Fase 1 definida no arquivo de referência. Os formatos reais foram inspecionados antes dos parsers; consulte [docs/file-format-findings.md](docs/file-format-findings.md).

## Subir com Docker Compose

```bash
docker compose up --build
```

Swagger: `http://localhost:8000/docs`. Liveness: `GET /health`. Readiness com banco: `GET /api/v1/health/ready`.

Copie `Deadside.zip` para `sample-data/Deadside.zip` e importe:

```bash
docker compose exec api python -m app.cli import-zip /data/Deadside.zip --server-slug brasil-deadside-01 --server-name "Brasil Deadside"
```

O comando pode ser repetido: SHA-256 e a chave `(server_id, remote_path)` tornam a importação idempotente. Um JSON inválido registra erro em `remote_files`, mas não substitui `characters_current` ou `vehicles_current`.

## Execução local

Requer Python 3.12 e PostgreSQL.

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
copy .env.example .env
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload
```

Testes: `pytest -q`. Cobertura: `pytest --cov=app --cov-report=term-missing -q` (mínimo de 70%).

## Deploy em produção (Railway)

O repositório inclui `Dockerfile`, `.dockerignore` e `railway.json`. O contêiner executa as migrações antes de iniciar a API, roda com usuário sem privilégios e usa a porta fornecida pelo Railway.

Configure no serviço, no mínimo:

```dotenv
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://usuario:senha@host:porta/banco
CORS_ALLOWED_ORIGINS=https://painel.seudominio.com,https://admin.seudominio.com
CORS_ALLOW_CREDENTIALS=false
WEBSOCKET_ALLOWED_ORIGINS=https://painel.seudominio.com,https://admin.seudominio.com
WEBSOCKET_ALLOW_MISSING_ORIGIN=false
TRUSTED_HOSTS=sua-api.up.railway.app
FORCE_HTTPS=true
FTP_HOST=seu-host
FTP_PORT=28221
FTP_USERNAME=seu-usuario
FTP_PASSWORD=sua-senha
WEBSOCKET_JWT_SECRET=gere-um-segredo-aleatorio-forte
```

O Railway injeta `PORT`; não fixe esse valor em produção. O healthcheck de deploy usa `GET /health`. O endpoint `GET /api/v1/health/ready` também verifica a conexão com PostgreSQL.

O rate limit protege as mutações de FTP e sincronização. Ele é local ao processo; mantenha um worker por instância ou use um backend compartilhado, como Redis, antes de escalar horizontalmente.

## CORS, navegador e proxy

A API usa Bearer JWT, não cookies de sessão; por isso `CORS_ALLOW_CREDENTIALS=false` é o padrão. O frontend deve enviar `Authorization: Bearer TOKEN` em `fetch` ou Axios sem `credentials: "include"`/`withCredentials`. Se cookies forem adotados futuramente, use origens explícitas, `CORS_ALLOW_CREDENTIALS=true`, HTTPS, `Secure`, `HttpOnly` e `SameSite=None` quando o uso for realmente cross-site.

As listas CSV de origens removem espaços, duplicados e somente a barra final. Cada origem continua sendo exata: protocolo, hostname e porta. Configurações com path, query, fragmento, credenciais embutidas ou esquema diferente de HTTP(S) impedem a inicialização. Em produção, `*`, listas vazias e regex totalmente permissivas também são rejeitadas.

O FastAPI é a única camada responsável pelos headers CORS. Em Railway, Cloudflare, Nginx ou outro proxy, preserve `Origin`, `Authorization`, `Upgrade`, `Connection`, `X-Forwarded-Proto`, `X-Forwarded-Host` e `X-Forwarded-For`, mas não adicione outro `Access-Control-Allow-Origin`. Headers duplicados são rejeitados pelos navegadores.

Preflights `OPTIONS` são respondidos antes de autenticação, banco e regra de negócio. A aplicação não redireciona barras finais; use exatamente as URLs documentadas. O endpoint seguro `GET /api/v1/diagnostics/cors` mostra a configuração efetiva sem tokens, cookies ou senhas.

Para testar pelo navegador:

```bash
python -m http.server 5173 --directory scripts
```

Abra `http://localhost:5173/cors_test.html`. A página permite testar GET, POST, headers acessíveis e WebSocket. Ela está em [scripts/cors_test.html](scripts/cors_test.html).

Em páginas HTTPS, use a API em `https://` e WebSocket em `wss://`; chamar `http://` ou `ws://` é mixed content e pode ser bloqueado antes de CORS. Em desenvolvimento HTTP, use `ws://`.

### Diagnóstico de CORS no navegador

1. `No Access-Control-Allow-Origin header`: a origem exata não está autorizada.
2. `Response to preflight doesn't pass access control check`: `OPTIONS`, método ou header solicitado não foi permitido.
3. `Request header field authorization is not allowed`: confirme `Authorization` em `CORS_ALLOWED_HEADERS`.
4. `Credential is not supported with wildcard`: nunca combine `*` com credentials; esta API falha ao iniciar nessa configuração.
5. `Mixed Content`: o frontend HTTPS está chamando uma API HTTP ou um WebSocket `ws://`.
6. `WebSocket connection failed`: confira `ws/wss`, a allowlist de Origin, JWT e headers `Upgrade`/`Connection` no proxy.
7. `Multiple values in Access-Control-Allow-Origin`: proxy e FastAPI estão adicionando CORS simultaneamente.
8. `Redirect is not allowed for preflight`: confira barra final e redirecionamento HTTP→HTTPS no proxy. O preflight deve chegar pela URL HTTPS final.
9. CORS escondendo um 500: consulte os logs; o middleware externo mantém CORS e o JSON sanitizado também em falhas inesperadas.
10. `Failed to fetch`: também pode indicar DNS, TLS, mixed content, conexão recusada ou backend offline; não é necessariamente CORS.

## Integração FTP (somente leitura)

Copie `.env.example` para `.env` e defina, no mínimo, as variáveis abaixo. Nunca versione o `.env` ou coloque a senha em logs e documentação.

```dotenv
FTP_PROTOCOL=ftp
FTP_HOST=seu-host
FTP_PORT=28221
FTP_USERNAME=seu-usuario
FTP_PASSWORD=sua-senha
FTP_USE_TLS=false
FTP_PASSIVE_MODE=true
FTP_ROOT_PATH=/
```

Após criar o servidor pela API, use seu UUID ou `slug` nos comandos:

```bash
# Testar autenticação e leitura da raiz
curl -X POST http://localhost:8000/api/v1/servers/SEU_SERVIDOR/ftp/test

# Descobrir e persistir a estrutura remota
curl -X POST http://localhost:8000/api/v1/servers/SEU_SERVIDOR/ftp/discover

# Executar uma sincronização manual
curl -X POST http://localhost:8000/api/v1/servers/SEU_SERVIDOR/sync/run

# Iniciar e parar o polling contínuo
curl -X POST http://localhost:8000/api/v1/servers/SEU_SERVIDOR/sync/start
curl -X POST http://localhost:8000/api/v1/servers/SEU_SERVIDOR/sync/stop

# Consultar estado e contadores
curl http://localhost:8000/api/v1/servers/SEU_SERVIDOR/sync/status
```

O sincronizador compara caminho, tamanho e data de modificação, aguarda estabilidade do arquivo, valida o tamanho baixado e usa SHA-256 antes de chamar os parsers e a ingestão já existentes. Downloads são temporários e nenhuma operação de escrita remota é exposta pelo cliente FTP.

## WebSocket em tempo real

Execute `alembic upgrade head` para criar `domain_events` e a sequência persistente por servidor. Defina um segredo HS256 forte somente no `.env` real:

```dotenv
WEBSOCKET_ENABLED=true
WEBSOCKET_JWT_SECRET=gere-um-segredo-aleatorio-forte
WEBSOCKET_PERSIST_EVENTS=true
```

Os quatro canais são:

```text
WS /api/v1/servers/{server_id}/ws/kills
WS /api/v1/servers/{server_id}/ws/map
WS /api/v1/servers/{server_id}/ws/sync
WS /api/v1/servers/{server_id}/ws/events
```

O JWT deve usar HS256 e conter `sub`, `role`, `server_ids` e `exp`. Papéis aceitos: `PUBLIC`, `MAP_VIEWER`, `MODERATOR`, `SERVER_ADMIN` e `SUPER_ADMIN`. Envie preferencialmente `Authorization: Bearer JWT`; clientes sem suporte a headers podem usar temporariamente `?token=JWT`. Tokens em logs são mascarados.

Eventos incluem `kill.created`, `death.created`, `character.created`, `character.updated`, `character.position.updated`, `vehicle.created`, `vehicle.updated`, `vehicle.position.updated`, `vehicle.disappeared`, `storage.updated`, `sync.started`, `sync.progress`, `sync.completed`, `sync.failed`, `ftp.connected` e `ftp.disconnected`. A publicação ocorre somente depois do commit. Hashes, fingerprints e posições idênticas não geram duplicatas.

O servidor envia `system.ping`; responda com `{"event":"system.pong"}`. Na reconexão, passe `after_sequence`. Se o histórico não estiver disponível, o servidor envia `system.resync_required` e o frontend deve recarregar o estado pelos endpoints REST.

```javascript
const ws = new WebSocket(
  "ws://localhost:8000/api/v1/servers/SEU_SERVIDOR/ws/kills?token=JWT"
);

ws.onmessage = ({ data }) => {
  const message = JSON.parse(data);
  if (message.event === "system.ping") {
    ws.send(JSON.stringify({ event: "system.pong" }));
  } else if (message.event === "kill.created") {
    console.log("Nova kill", message.data);
  }
};
```

```python
import asyncio
import json
import websockets

async def main():
    uri = "ws://localhost:8000/api/v1/servers/SEU_SERVIDOR/ws/kills?token=JWT"
    async with websockets.connect(uri) as websocket:
        async for raw in websocket:
            message = json.loads(raw)
            if message["event"] == "system.ping":
                await websocket.send(json.dumps({"event": "system.pong"}))
            else:
                print(message)

asyncio.run(main())
```

No canal geral, assine apenas eventos necessários:

```json
{"action":"subscribe","events":["kill.created"],"filters":{"player_id":"123"}}
```

Status e recuperação REST:

```text
GET /api/v1/servers/{server_id}/ws/status
GET /api/v1/servers/{server_id}/events?after_sequence=100
```

Limites padrão: 500 conexões por servidor, 10 por usuário, mensagens de 64 KiB, timeout de envio de 5 segundos, heartbeat de 25 segundos e retenção de eventos por 24 horas. Códigos relevantes: `1000` encerramento normal, `1008` política/limite, `1011` falha interna, `4401` não autenticado e `4403` sem permissão. WebSocket é incremental: os endpoints REST continuam sendo a fonte canônica e devem ser usados como fallback.

## Referência completa dos endpoints

### Convenções usadas pela API

- URL local: `http://localhost:8000`; prefixo REST: `/api/v1`.
- `{server_id}` aceita tanto o UUID quanto o `slug` cadastrado em `/servers`.
- `{player_id}` vem do nome do arquivo `.sav` do personagem, sem a extensão.
- Datas são retornadas em ISO 8601. Datas dos deathlogs sem timezone são interpretadas como UTC.
- Listas vazias significam que nenhum dado correspondente já foi sincronizado; não significam necessariamente erro.
- Erros HTTP usam `{"error":"mensagem","status":400}`. Validação inclui também `details`.
- `404` normalmente indica servidor ou entidade inexistente; `422`, parâmetro inválido; `429`, excesso de chamadas críticas; `500`, falha interna sanitizada.
- As respostas representam o último estado processado no PostgreSQL. Para obter dados novos do FTP, execute ou mantenha ativa a sincronização.
- Senhas FTP, JWT, `LockPassword` e campos sensíveis encontrados nos JSON nunca são expostos pelos endpoints comuns.

Documentação interativa: `GET /docs` (Swagger) e `GET /openapi.json`.

### De onde vêm os dados do FTP

Os nomes `actual1`, `characters1-9`, `new_vehicles1-9` e `storages1-9` abaixo representam a estrutura observada nos arquivos reais. O descobridor procura as categorias pelo nome, portanto o caminho raiz anterior pode variar conforme a hospedagem.

| Categoria | Padrão observado no FTP | Formato | Endpoints alimentados |
|---|---|---|---|
| Personagem atual | `Deadside/Saved/actual1/characters1-9/world_0/{player_id}.sav` | JSON UTF-8, apesar da extensão `.sav` | `/characters`, `/map/entities` e eventos de personagem |
| Personagem permanente | `Deadside/Saved/actual1/characters_nowipe/{player_id}.sav` | JSON UTF-8 | `/characters/{player_id}/permanent` |
| Veículos | `Deadside/Saved/actual1/new_vehicles1-9/world_0/new_vehicles.sav` | JSON UTF-8 com `Count` e objetos `VehicleN` | `/vehicles`, `/map/entities` e eventos de veículo |
| Storages | `Deadside/Saved/actual1/storages1-9/world_0/{player_id}_itemstorage_...sav` | JSON UTF-8 | `/storages` e eventos de storage |
| Mortes e kills | `Deadside/Saved/actual1/deathlogs/world_0/*.csv` | CSV sem cabeçalho, dez colunas separadas por `;` | `/kills`, `/players/...` e eventos de combate |
| Bases | caminhos cujo arquivo começa com `bases` | Binário | Apenas inventário técnico como `metadata_only`; sem endpoint de conteúdo |
| Configuração | `admin.conf`, `server.info`, `config/LinuxServer/...` | INI/texto | Descoberta técnica; sem endpoint de conteúdo nesta versão |
| Logs | diretórios `logs`, arquivos `.log` | Texto | Descoberta técnica; sem endpoint de conteúdo nesta versão |

O ciclo de ingestão compara caminho, tamanho e data de modificação, aguarda o arquivo estabilizar, baixa para um diretório temporário, valida o tamanho e calcula SHA-256. Arquivos inalterados são ignorados. JSON inválido ou arquivo parcialmente escrito não substitui o último estado válido.

### Saúde, versão e diagnósticos

| Método e endpoint | Fonte FTP | O que retorna |
|---|---|---|
| `GET /health` | Nenhuma | Liveness simples para Railway/Docker: `{"status":"ok"}`. Não consulta o banco. |
| `GET /api/v1/health` | Nenhuma | Mesmo healthcheck no namespace versionado. |
| `GET /api/v1/health/ready` | Nenhuma | Executa `SELECT 1`. Retorna 200 com banco conectado ou 503 com `database: "disconnected"`. |
| `GET /api/v1/version` | Nenhuma | Nome e versão da API em execução. |
| `GET /api/v1/diagnostics/parsers` | Relaciona-se às cinco categorias interpretadas | Lista nome, versão e estado dos parsers de personagem, nowipe, veículo, storage e deathlog. |
| `GET /api/v1/diagnostics/cors` | Nenhuma | Mostra ambiente, origens, métodos, headers e política de Origin do WebSocket. Não retorna secrets. |

### Cadastro lógico de servidores

O servidor é o namespace que separa os dados no banco. As credenciais FTP continuam vindo das variáveis `FTP_*` da instância da API; criar um servidor não grava a senha enviada pelo frontend.

| Método e endpoint | Corpo/parâmetros | Resultado |
|---|---|---|
| `GET /api/v1/servers` | Nenhum | Lista servidores ordenados por nome. |
| `POST /api/v1/servers` | JSON `{"slug":"brasil-01","name":"Brasil 01"}` | Cria o namespace e retorna 201. O slug aceita letras minúsculas, números e hífens; duplicado retorna 409. |
| `GET /api/v1/servers/{server_id}` | UUID ou slug na URL | Retorna `id`, `slug`, `name` e `enabled`; inexistente retorna 404. |
| `PATCH /api/v1/servers/{server_id}` | JSON parcial com `name` e/ou `enabled` | Renomeia ou ativa/desativa o cadastro. |
| `DELETE /api/v1/servers/{server_id}` | Nenhum | Exclui o servidor e os dados relacionados por cascade; retorna 204 sem corpo. |

```bash
curl -X POST http://localhost:8000/api/v1/servers \
  -H "Content-Type: application/json" \
  -d '{"slug":"brasil-01","name":"Servidor Brasil 01"}'
```

### Conexão FTP e sincronização

Todos estes endpoints usam as credenciais `FTP_HOST`, `FTP_PORT`, `FTP_USERNAME`, `FTP_PASSWORD`, `FTP_PROTOCOL` e `FTP_ROOT_PATH`. As operações remotas são somente leitura.

| Método e endpoint | Ação | Resposta importante |
|---|---|---|
| `POST /api/v1/servers/{server_id}/ftp/test` | Autentica e lista a raiz configurada, sem importar arquivos. | `success`, protocolo, host mascarado, porta, autenticação, modo passivo, quantidade de entradas e latência. |
| `POST /api/v1/servers/{server_id}/ftp/discover` | Percorre a árvore até `FTP_DISCOVERY_MAX_DEPTH` e identifica personagens, nowipe, veículos, storages, deathlogs, configs, bases e logs. | `paths`, `entries_scanned` e `files_monitored`. |
| `GET /api/v1/servers/{server_id}/ftp/status` | Consulta o estado do sincronizador em memória. | Estado, conexão, última verificação/sucesso/erro e contadores. |
| `GET /api/v1/servers/{server_id}/sync/status` | Alias do endpoint anterior. | Mesmo contrato de `/ftp/status`. |
| `POST /api/v1/servers/{server_id}/sync/run` | Executa exatamente um ciclo completo de descoberta, comparação, download e ingestão. | `status`, `scanned`, `changed`, `processed`, `failed`, `skipped` e `duration_ms`. |
| `POST /api/v1/servers/{server_id}/sync/start` | Inicia polling contínuo no processo atual. | `status: "started"` ou `already_running`, mais o estado atual. |
| `POST /api/v1/servers/{server_id}/sync/stop` | Cancela o polling contínuo. | `status: "stopped"` e estado final. |

Falhas esperadas de FTP são devolvidas de forma segura como `success: false`, `error_code`, `message` e `tested_at`, sem host completo, usuário ou senha. Os endpoints mutáveis têm rate limit. O estado de polling é local ao processo e reinicia quando a instância reinicia.

```bash
curl -X POST http://localhost:8000/api/v1/servers/brasil-01/ftp/test
curl -X POST http://localhost:8000/api/v1/servers/brasil-01/ftp/discover
curl -X POST http://localhost:8000/api/v1/servers/brasil-01/sync/run
curl http://localhost:8000/api/v1/servers/brasil-01/sync/status
```

### Personagens atuais

Fonte: `characters1-9/world_0/{player_id}.sav`. O parser lê `BaseCharacter.Login`, `Map`, `PosX/Y/Z`, `RotYaw`, `Health`, `ACBaseInventory` e `ACInventory`. A API não afirma que o jogador está online; ela informa a idade do arquivo.

| Método e endpoint | Parâmetros | Resultado |
|---|---|---|
| `GET /api/v1/servers/{server_id}/characters` | `limit` de 1 a 1000; padrão 100 | Lista o estado corrente dos personagens já importados. |
| `GET /api/v1/servers/{server_id}/characters/{player_id}` | ID derivado do nome do `.sav` | Retorna um personagem; 404 quando ainda não foi importado. |
| `GET /api/v1/servers/{server_id}/characters/{player_id}/permanent` | Mesmo `player_id` | Usa o arquivo de `characters_nowipe` e retorna login, achievements, quantidade e progression separadamente do estado atual. |

Campos de posição incluem `world_position` e `map_position`; dentro de `map_position` ficam `x`, `y`, `inside_map` e `grid`. A resposta também inclui `source_age_seconds` e `position_freshness`. A frescura é `fresh` até 15 s, `delayed` até 120 s e `stale` depois disso. `observed_at` é quando a API processou o estado; `source_modified_at`, quando disponível, vem do FTP.

Exemplo resumido:

```json
{
  "player_id": "ID_DO_ARQUIVO",
  "login": "Jogador",
  "map_name": "world_0",
  "pos_x": 12345.0,
  "pos_y": -67890.0,
  "pos_z": 250.0,
  "health": 100.0,
  "inventory": {},
  "map_position": {"x": 553.1, "y": -880.2, "inside_map": true, "grid": "H7"},
  "position_freshness": "fresh"
}
```

### Veículos

Fonte: `new_vehicles1-9/world_0/new_vehicles.sav`. Cada `VehicleN` precisa ter `Vehicle.VehicleUID`. São lidos `ActorID`, posição `X/Y/Z`, quaternion, `RotYaw`, `Fuel`, `Durability`/`Drb`, `LockValue` e inventário. `LockPassword` é removido das respostas.

| Método e endpoint | Parâmetros | Resultado |
|---|---|---|
| `GET /api/v1/servers/{server_id}/vehicles` | `active=true|false` opcional; `limit` de 1 a 1000 | Lista veículos atuais. Veículo que some de um snapshot completo pode ficar `active=false` com `missing_since`. |
| `GET /api/v1/servers/{server_id}/vehicles/{vehicle_uid}` | UID real do JSON | Retorna veículo, combustível, durabilidade, rotação, inventário e posição convertida; 404 se desconhecido. |

`display_name` é derivado de `ActorID` para facilitar a interface. `metadata` e `raw_data` internos não são devolvidos. A resposta inclui a mesma informação de mapa e frescura usada em personagens.

### Storages

Fonte: `storages1-9/world_0/*.sav`. O nome normalmente segue `{player_id}_itemstorage_{world}_{grid}_{storage_type}.sav`; dele são extraídos proprietário, mundo, grid e tipo. O objeto `Inventory` contém `ItemN` com `Index`, `Count`, `Durability`, `Skin`, `Ammo`, `Level` e modificadores quando presentes.

| Método e endpoint | Parâmetros | Resultado |
|---|---|---|
| `GET /api/v1/servers/{server_id}/storages` | `player_id` opcional; `limit` de 1 a 1000 | Lista storages por observação mais recente. |
| `GET /api/v1/servers/{server_id}/storages/{storage_id}` | Nome do arquivo sem `.sav` | Retorna um storage específico; 404 se desconhecido. |

Exemplo resumido:

```json
{
  "storage_id": "123_itemstorage_world_0_X08_Y07_ItemStorage01_2",
  "player_id": "123",
  "world": "world_0",
  "grid": "X08_Y07",
  "storage_type": "ItemStorage01_2",
  "items": [{"Index": 10, "Count": 2, "Durability": 95}],
  "item_count": 1,
  "observed_at": "2026-07-21T22:15:00Z"
}
```

### Deathlogs, kills e estatísticas de combate

Fonte: `deathlogs/world_0/*.csv`. Os arquivos reais possuem dez colunas: data/hora, nome e ID do killer, nome e ID da vítima, arma/causa, distância, plataforma do killer, plataforma da vítima e campo reservado. A API classifica `player_kill`, `suicide`, `environmental_death`, `npc_kill`, `killed_by_npc` e `unknown_death`, normaliza nomes e deduplica eventos por fingerprint.

Os deathlogs reais não fornecem coordenadas, grid ou timezone. A API não usa a última posição do personagem como posição da morte.

| Método e endpoint | Parâmetros | Resultado |
|---|---|---|
| `GET /api/v1/servers/{server_id}/kills` | `from`, `to`, `killer_id`, `killer_name`, `victim_id`, `victim_name`, `weapon`, `grid`, `min_distance`, `max_distance`, `limit` 1–1000, `offset`, `sort=event_time|distance`, `order=asc|desc` | Pesquisa apenas kills PvP, com filtros combináveis e paginação. |
| `GET /api/v1/servers/{server_id}/kills/latest` | `limit` 1–100; padrão 20 | Últimas kills PvP por data decrescente. |
| `GET /api/v1/servers/{server_id}/kills/feed` | `limit` 1–100 | Mesmo conjunto de `latest`, acrescido de `message` pronto para feed. |
| `GET /api/v1/servers/{server_id}/kills/statistics` | Nenhum | Conta todos os eventos por tipo e calcula kills PvP, distância média e maior distância. |
| `GET /api/v1/servers/{server_id}/kills/leaderboard` | `period=today|week|month|all`, `sort=kills|deaths|kd_ratio|longest_kill`, `limit`, `offset` | Ranking agregado. K/D informa também `kd_eligible`, controlado por `KILLS_LEADERBOARD_MIN_KILLS_FOR_KD`. |
| `GET /api/v1/servers/{server_id}/kills/weapons` | Nenhum | Kills, percentual, distância média e maior distância agrupados por arma. |
| `GET /api/v1/servers/{server_id}/kills/timeline` | `interval=hour|day|week`, `from`, `to` | Série temporal de kills PvP agrupadas no intervalo solicitado. |
| `GET /api/v1/servers/{server_id}/kills/head-to-head` | Obrigatórios `player_a` e `player_b` | Quantas vezes A matou B e B matou A. Aceita os identificadores usados no deathlog. |
| `GET /api/v1/servers/{server_id}/kills/geojson` | Nenhum | GeoJSON quando houver coordenadas. Para os arquivos reais atuais retorna `available:false` e a razão. |
| `GET /api/v1/servers/{server_id}/kills/heatmap` | Nenhum | Pontos com peso para heatmap quando houver coordenadas; atualmente indisponível pelo mesmo limite do CSV. |
| `GET /api/v1/servers/{server_id}/kills/{kill_id}` | UUID interno da kill | Evento PvP individual; 404 para UUID inexistente ou evento que não seja kill PvP. |

Exemplo de filtro:

```text
GET /api/v1/servers/brasil-01/kills?from=2026-07-01T00:00:00Z&weapon=AK&min_distance=50&limit=50&sort=distance&order=desc
```

Exemplo resumido de evento:

```json
{
  "id": "UUID",
  "event_time": "2026-07-21T20:10:00Z",
  "event_type": "player_kill",
  "killer_id": "EOS_ID",
  "killer_name": "Killer",
  "victim_id": "EOS_ID",
  "victim_name": "Victim",
  "weapon_name": "AK-Mod",
  "distance_meters": 125.4,
  "killer_platform": "PS5",
  "victim_platform": "XSX",
  "map_x": null,
  "map_y": null,
  "source_file": "/Deadside/Saved/actual1/deathlogs/world_0/arquivo.csv",
  "source_line": 1
}
```

### Estatísticas por jogador

Todos os endpoints abaixo são derivados dos mesmos CSVs de deathlog. `{player_id}` normalmente é o ID EOS; quando o evento não possui ID, o serviço consegue comparar o nome normalizado.

| Método e endpoint | Resultado |
|---|---|
| `GET /api/v1/servers/{server_id}/players/{player_id}/kills` | Todas as kills PvP realizadas pelo jogador, mais recentes primeiro. |
| `GET /api/v1/servers/{server_id}/players/{player_id}/deaths` | Mortes do jogador, incluindo os tipos presentes no deathlog. |
| `GET /api/v1/servers/{server_id}/players/{player_id}/combat-stats` | `kills`, `deaths`, `suicides`, `npc_kills`, `deaths_by_npc`, mortes ambientais, K/D, invicto, distâncias e arma favorita. |
| `GET /api/v1/servers/{server_id}/players/{player_id}/rivals` | Adversários ordenados pela soma de encontros fatais nos dois sentidos. |
| `GET /api/v1/servers/{server_id}/players/{player_id}/victims` | Vítimas mais eliminadas pelo jogador e contagem de kills. |
| `GET /api/v1/servers/{server_id}/players/{player_id}/killers` | Jogadores que mais eliminaram o jogador consultado e contagem de mortes. |

Quando `deaths` é zero, `kd_ratio` é `null` e `undefeated` é `true`; a API não retorna infinito.

### Mapa e coordenadas

As posições vêm dos JSON de personagens e veículos. A imagem não vem do FTP: foi montada localmente a partir dos nove tiles fornecidos, sem hotlink.

| Método e endpoint | Entrada | Resultado |
|---|---|---|
| `GET /api/v1/servers/{server_id}/map/config` | Nenhuma | Versão da calibração, bounds, origem, escala, URL da imagem e template dos tiles. |
| `POST /api/v1/servers/{server_id}/map/convert` | JSON `{"x":12345,"y":-67890,"z":250}` em coordenadas Unreal | `world_position` e `map_position`; esta última contém `inside_map` e `grid`. |
| `POST /api/v1/servers/{server_id}/map/reverse-convert` | JSON `{"x":640,"y":-896}` no mapa | Coordenadas `x/y` aproximadas no mundo do jogo. |
| `GET /api/v1/servers/{server_id}/map/entities` | Nenhuma | Personagens com posição e veículos ativos com posição, prontos para marcadores. |
| `GET /api/v1/servers/{server_id}/map/live-players` | sem filtro obrigatório | Somente sessões confirmadas pelos marcadores `Join succeeded` e `has logged out` do `Saved/Logs/Deadside.log`. O monitor baixa apenas os saves desses jogadores em `characters*/world_*`, com alvo de `FTP_LIVE_POSITION_INTERVAL_SECONDS=0.5`, e publica `character.position.sampled` no WebSocket. Veículos e jogadores desconectados nunca entram nesta resposta. |
| `GET /api/v1/maps/mirny/image` | Nenhuma | PNG consolidado 1280×1408, com cache público de 24 horas e `Content-Disposition`. |
| `GET /static/maps/mirny/tiles/map_{x}_{y}.png` | `x` e `y` de 0 a 2 no caminho | Tile original 512×512. Arquivo inexistente retorna 404. |

### Eventos REST e WebSocket

Os eventos são gerados depois do commit de uma sincronização. Assim, uma mensagem WebSocket nunca anuncia uma alteração que ainda não foi confirmada no banco.

| Método e endpoint | Parâmetros/uso | Resultado |
|---|---|---|
| `GET /api/v1/servers/{server_id}/ws/status` | Nenhum | WebSocket habilitado, conexões por canal, última sequência e eventos persistidos na última hora. |
| `GET /api/v1/servers/{server_id}/events` | `after_sequence`, `event`, `entity_type`, `entity_id`, `from`, `to`, `limit` 1–1000 | Recuperação ordenada de eventos persistidos; serve para reconexão e fallback do frontend. |
| `WS /api/v1/servers/{server_id}/ws/kills` | JWT; role mínima `PUBLIC` | `kill.created` e eventos de morte destinados ao feed de combate. |
| `WS /api/v1/servers/{server_id}/ws/map` | JWT; role mínima `MAP_VIEWER` | Criação, atualização e mudança de posição de personagens/veículos. |
| `WS /api/v1/servers/{server_id}/ws/sync` | JWT; role `SERVER_ADMIN` ou `SUPER_ADMIN` | Progresso, conclusão, falha e conectividade FTP. |
| `WS /api/v1/servers/{server_id}/ws/events` | JWT; role mínima `MAP_VIEWER` | Canal geral com `subscribe`, `unsubscribe` e filtros permitidos. |

O navegador deve enviar um `Origin` presente em `WEBSOCKET_ALLOWED_ORIGINS`. O JWT pode vir em `Authorization: Bearer JWT`; a query `?token=JWT` existe apenas como fallback. Use `after_sequence=N` na reconexão. O servidor envia `system.ping`; responda `{"event":"system.pong"}`. Em produção HTTPS use `wss://`.

### Relação entre sincronização e consulta

```text
FTP somente leitura
  -> descoberta dos caminhos
  -> comparação de tamanho/data/hash
  -> parser conforme a categoria
  -> transação PostgreSQL
  -> estado REST atualizado
  -> evento WebSocket publicado após o commit
```

Fluxo recomendado para uma instalação nova:

1. Cadastre o servidor com `POST /api/v1/servers`.
2. Valide as credenciais com `POST /ftp/test`.
3. Confira os caminhos reconhecidos com `POST /ftp/discover`.
4. Execute `POST /sync/run` e verifique `processed`/`failed`.
5. Consulte personagens, veículos, storages e kills.
6. Quando estiver estável, use `POST /sync/start` para atualização contínua.
7. Use REST como fonte canônica e WebSocket apenas para atualizações incrementais.

## Segurança e limitações

A API não declara jogadores online com base apenas na idade do arquivo. O endpoint `map/live-players` reconstrói as sessões pelos eventos de entrada e saída do `Deadside.log`; `source_age_seconds` informa separadamente a idade da última amostra de posição. JWT, roles, auditoria e SFTP continuam fora desta fase. Antes de distribuir publicamente a imagem fornecida, confirme os direitos de uso.

## Montagem dos tiles do mapa

O script `montar_mapa_deadside.py` interpreta numericamente `map_x_y.png`: `x` cresce da esquerda para a direita e `y` de cima para baixo. Ele nunca redimensiona, rotaciona, espelha ou troca os eixos.

Instalação:

```bash
python -m pip install -r requirements.txt
```

Montagem limpa, sem recorte:

```bash
python montar_mapa_deadside.py --input-dir ./tiles --output deadside_map_full.png
```

Montagem dos tiles incluídos com os limites Leaflet exatos usados pela API:

```bash
python montar_mapa_deadside.py --input-dir app/static/maps/mirny/tiles --output app/static/maps/mirny/deadside_map.png --crop-mode manual --crop-left 0 --crop-top 0 --crop-right 1280 --crop-bottom 1408
```

Recorte automático das bordas externas pretas ou transparentes:

```bash
python montar_mapa_deadside.py --input-dir ./tiles --output deadside_map_auto.png --crop-mode auto --black-threshold 15
```

Recorte manual e diagnóstico da grade:

```bash
python montar_mapa_deadside.py --input-dir ./tiles --output deadside_map_cropped.png --crop-mode manual --crop-left 0 --crop-top 0 --crop-right 1280 --crop-bottom 1408 --debug-grid
```

Recorte central opcional para a proporção Leaflet 1280:1408:

```bash
python montar_mapa_deadside.py --input-dir ./tiles --output deadside_map_ratio.png --crop-to-leaflet-ratio
```
