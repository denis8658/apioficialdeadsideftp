# Formato real dos deathlogs do Deadside

Inspeção realizada em 21 de julho de 2026 sobre os arquivos disponíveis em `/Deadside/Saved/actual1/deathlogs/world_0` no FTP configurado. O conteúdo foi acessado somente para leitura.

## Arquivos e formato

- 19 arquivos `.csv`.
- 49 linhas completas no total.
- Encoding: UTF-8 com BOM (`utf-8-sig`).
- Delimitador: ponto e vírgula (`;`).
- Cabeçalho: ausente em todos os arquivos reais.
- Colunas: 10 em todas as linhas.
- Data: `YYYY.MM.DD-HH.MM.SS`.
- O arquivo não informa o fuso horário; a API normaliza o valor como UTC.

A ordem observada e confirmada pela documentação administrativa do Deadside é:

| Coluna | Campo | Presença real |
|---:|---|---|
| 1 | data e hora | sempre |
| 2 | nome do killer | sempre |
| 3 | ID EOS do killer | sempre, hexadecimal com 32 caracteres |
| 4 | nome da vítima | sempre |
| 5 | ID EOS da vítima | sempre, hexadecimal com 32 caracteres |
| 6 | arma ou causa | sempre |
| 7 | distância em metros | sempre, inclusive zero |
| 8 | plataforma do killer | sempre (`PS5` ou `XSX` na amostra) |
| 9 | plataforma da vítima | sempre (`PS5` ou `XSX` na amostra) |
| 10 | campo reservado | sempre vazio |

Referência complementar da ordem oficial das colunas: [Official Deadside Wiki — Server Admin Panel](https://officialdswiki.com/en/server_admin_panel).

## Classificação observada

| Tipo normalizado | Eventos |
|---|---:|
| `player_kill` | 2 |
| `suicide` | 29 |
| `environmental_death` | 18 |
| `npc_kill` | 0 |
| `killed_by_npc` | 0 |
| `unknown_death` | 0 |

As causas ambientais observadas foram `falling`. Foram encontrados suicídios explícitos por `suicide_by_relocation` e suicídios nos quais killer e vítima possuem o mesmo ID, inclusive com arma/explosivo. Uma kill PvP só é marcada quando os dois IDs representam jogadores distintos.

## Campos ausentes

Os arquivos reais não contêm:

- coordenadas da morte;
- posição do killer ou da vítima;
- identificador interno da arma separado do nome;
- grid do mapa;
- causa separada da coluna de arma;
- timezone explícito.

Consequentemente, GeoJSON e heatmap retornam `available: false`. A API não usa a última posição conhecida do personagem como localização da morte.

## Robustez e idempotência

O parser também aceita arquivos com cabeçalho, delimitadores `,`, `;`, tab ou `|`, e fallbacks de encoding UTF-8, CP-1252 e CP-1251. Linhas incompletas são ignoradas quando já existem linhas válidas; um arquivo sem qualquer evento completo é rejeitado como potencial escrita parcial.

O fingerprint é calculado com data, IDs ou nomes normalizados, arma/causa, distância e plataformas. Caminho e número da linha são preservados para auditoria, mas não participam da identidade do evento, permitindo deduplicar arquivos rotacionados ou recompostos.
