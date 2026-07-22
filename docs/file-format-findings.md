# Descobertas nos arquivos de referência

Fonte analisada: `Deadside.zip`, 236 entradas e 12.413.792 bytes descompactados.

## Inventário por conteúdo

| Formato detectado | Quantidade | Observação |
|---|---:|---|
| JSON | 149 | Inclui personagens, `characters_nowipe`, veículos e storages com extensão `.sav`. |
| CSV | 20 | Deathlogs sem cabeçalho, delimitados por ponto e vírgula. |
| Configuração/texto | 21 | `admin.conf`, `server.info`, INI e outros textos. |
| Binário | 45 | Principalmente snapshots de bases; tratados como `metadata_only`. |

Categorias observadas: 35 personagens, 35 nowipe, 70 storages, 2 arquivos de veículos (um deles vazio/estado mínimo), 20 deathlogs, 19 candidatos a configuração, 6 logs e 44 arquivos de bases.

## Campos reais encontrados

- Personagem: raiz `BaseCharacter` e `Character`. Em `BaseCharacter`: `Login`, `Skin`, `Pants`, `Map`, `PosX`, `PosY`, `PosZ`, `RotYaw`, `Pose`, `Health`, `ACBaseInventory`, `ACInventory`. Em `Character`: `Food`, `Water`, `Reputations`, DLCs, respawn, tutorial e blueprints.
- Nowipe: `BaseCharacter.Login` e `Character.Achievements`. Não é mesclado automaticamente com o estado corrente.
- Veículo: `Count` e `VehicleN`; posição `X/Y/Z`; quaternion `qX/qY/qZ/qW`; conteúdo interno com `Drb`, `Fuel`, `LockValue`, `LockPassword`, `VehicleCustomizationData`, `VehicleUID` e `Inventory`.
- Storage: raiz `Inventory`, itens `ItemN` com campos como `Index`, `Count`, `Durability`, `Skin`, `Ammo`, `Level` e modificadores de arma.
- Deathlog: linhas sem cabeçalho com 10 colunas delimitadas por `;`. Os dados reais não fornecem coordenadas; nenhuma é inferida.
- Configuração: `admin.conf` usa seções INI, contadores e chaves indexadas. Foram observadas entradas administrativas duplicadas em índices diferentes; o sistema não corrige o arquivo remoto.

## Divergências e limites

- A extensão `.sav` não indica binário: a maioria das amostras é JSON UTF-8 legível.
- O ZIP não contém `deadside_map.png`. Posteriormente foram fornecidos nove tiles `map_0_0.png` a `map_2_2.png`; eles foram posicionados por coluna/linha e recortados ao limite lógico em um PNG 1280×1408. A área restante dos tiles de borda era padding transparente. Os tiles 512×512 também foram preservados individualmente. Não há hotlink.
- As bases são binárias. Na Fase 1 ficam em `metadata_only`, com caminho, tamanho e SHA-256 no registro remoto. Não são inventadas coordenadas.
- Deathlogs não têm cabeçalho e não trazem coordenadas nas amostras.
- `LockPassword` existe no arquivo real. É preservado apenas no `raw_data` interno e nunca serializado por endpoints comuns.
- FTP/FTPS/SFTP, storages, deaths, logs, configurações, autenticação e WebSocket pertencem às fases posteriores definidas na própria referência.

## Arquivos não interpretados na Fase 1

- Todos os `other1-9/world_0/bases*`: binários, `metadata_only`.
- `other/world_0/bases`: estado mínimo/binário, `metadata_only`.
- `characters_nowipe/*.sav`, `storages1-9/*.sav`, `deathlogs/*.csv`, configurações e logs: formato reconhecido, parser de domínio programado para fases posteriores.
- `new_vehicles/world_0/new_vehicles.sav`: estado mínimo separado do snapshot principal; não corresponde ao padrão versionado `new_vehicles1-9` da Fase 1.
