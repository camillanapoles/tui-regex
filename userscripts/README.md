# USHub · um botão, todos os seus userscripts (Android)

[![test](https://github.com/camillanapoles/tui-regex/actions/workflows/test.yml/badge.svg)](https://github.com/camillanapoles/tui-regex/actions/workflows/test.yml)

`ushub.user.js` é um **userscript-hub para mobile**: ele cria em toda página um
**botão flutuante de máxima usabilidade** que, ao ser tocado, abre um painel com
**todos os seus userscripts em um único local** — o catálogo é gerenciado por um
**gist público**: um `hub.json` (gestão/objeto) + **N arquivos `.user.js`** no
mesmo gist.

```
┌──────────────────────────────────────────────┐
│  GIST PÚBLICO (a "gestão objeto")            │
│  ├── hub.json ............ manifesto JSON    │
│  ├── leitor-conforto.user.js                 │
│  ├── voltar-ao-topo.user.js                  │
│  └── modo-noturno.user.js                    │
└──────────────┬───────────────────────────────┘
               │ api.github.com/gists/:id (1 chamada)
               ▼
┌──────────────────────────────────────────────┐
│  USHub no celular                            │
│  ( • ) FAB arrastável  →  bottom sheet       │
│        Catálogo · Instalar/Atualizar/Copiar  │
└──────────────────────────────────────────────┘
```

## Instalação (Android)

1. **Firefox para Android** + extensão **Tampermonkey** (ou Violentmonkey).
2. Instale `ushub.user.js` (abra o arquivo raw deste repositório — o gerenciador
   intercepta `.user.js` automaticamente).
3. Abra qualquer site e toque no **botão flutuante `</>`** — o **catálogo de
   fábrica** (este repositório, via `raw.githubusercontent.com`) já carrega os
   3 scripts de exemplo **sem configurar nada**.
4. Toque **Instalar** — o gerenciador abre a tela de instalação (a “captura
   real” dos scripts, a partir de um único lugar).

### Catálogo PRÓPRIO (opcional) — gestão via gist público

1. Crie um **gist público** em `gist.github.com` com `hub.json` + quantos
   `.user.js` quiser, no **mesmo gist** (use `userscripts/gist/` como modelo).
2. No painel → **Ajustes** → cole a **URL do gist** (ou ID, ou a URL crua do
   `hub.json` de qualquer repo/host estático — arquivos-irmãos são resolvidos)
   → **Salvar e carregar**. Campo vazio restaura o catálogo de fábrica.

### Validar no celular SEM instalar nada (demo)

`npm run demo` sobe uma página que executa o `ushub.user.js` **real** com
`GM_*` emulados (`demo/index.html` + `demo/dev-server.mjs`). Abra o endereço
no navegador do Android e rode o checklist de toques da própria página.

## Por que as decisões de UX são assim

| Decisão | Motivo |
| --- | --- |
| FAB **arrastável** com encaixe na borda mais próxima | Um botão fixo **sempre cobre algum texto** em algum site; aqui o usuário decide onde ele não atrapalha, e a posição é persistida. |
| FAB fica **translúcido (38%) após 4 s** parado | Botão parado não disputa atenção com o conteúdo; volta a 100% no primeiro toque. |
| **Some quando o teclado abre** (via `visualViewport`) | Nunca fica por cima do campo onde a pessoa digita. |
| Alvos de toque **≥ 48 px** (`--touch`) | WCAG 2.5.5 / Material: polegar real, sem erro de toque. |
| **Bottom sheet** com scrim e **deslizar-para-fechar** | Padrão nativo do Android; alcance do polegar, sem ir ao topo da tela. |
| **A− / A+** (85 %–140 %), persistido | Tamanho de fonte é personal da usuária — todo o painel deriva de `--fs`. |
| Tema **Auto/Claro/Escuro**, contraste 15:1 / 13:1 | Muito acima do mínimo WCAG AAA 4.5:1; respeita `prefers-color-scheme`. |
| `prefers-reduced-motion` zera animações | Conforto para quem tem sensibilidade a movimento. |
| **Shadow DOM** | O CSS da página nunca quebra o botão/painel e vice-versa. |
| Cache de **15 min** + exibição offline | Catálogo abre instantâneo mesmo sem sinal; avisa quando está em cache. |
| Busca **sem acentos**, com foco estável | “navegacao” acha “navegação”; o cursor não pula enquanto digita. |

## Esquema do `hub.json`

```jsonc
{
  "hub": "Nome do catálogo",
  "scripts": [
    {
      "id": "leitor-conforto",          // obrigatório, único
      "name": "Leitor Conforto",        // obrigatório
      "emoji": "📖",                     // opcional
      "version": "1.0.0",               // obrigatório (semver) → selo ⬆ de update
      "description": "...",             // recomendado
      "file": "leitor-conforto.user.js",// nome EXATO do arquivo no mesmo gist
      "tags": ["leitura"],              // opcional, entra na busca
      "author": "@voce"                 // opcional
    }
  ]
}
```

> **Regra de ouro do gist:** ele não tem pastas — o valor de `file` precisa ser
> o nome do arquivo **exatamente** como aparece no gist (diferencia maiúsculas).

## Gestão / versionamento

- **Lançar script novo:** adicione o `.user.js` no gist + uma entrada no `hub.json`.
- **Atualizar:** edite o arquivo no gist e **suba o `version`** no manifesto —
  o selo ⬆ e o contador no FAB aparecem sozinhos no próximo refresh.
- **Estado “instalado”** é registro local do aparelho (otimista): serve para
  comparar versões e exibir selos; não consulta o gerenciador.
- Fonte aceita: URL da página do gist, **ID do gist** ou URL crua do `hub.json`.

## Solução de problemas

- **“Esse gist não tem hub.json”** → o manifesto precisa se chamar `hub.json`
  (qualquer `.json` funciona como fallback, mas padronize).
- **Limite da API do GitHub** (60 req/h por IP sem token) → o cache de 15 min já
  mitiga; se estourar, aguarde a janela ou distribua a URL crua como fonte.
- **Popup bloqueado ao instalar** → use o botão **Código** (copia o fonte) e
  cole no editor do gerenciador.
- **Outro domínio de hospedagem** → adicione-o à diretiva `@connect` do
  `ushub.user.js` (gists oficiais já vão liberados).

## Estrutura do repositório

```
userscripts/
├── ushub.user.js            ← o hub (instale ESTE no celular)
├── gist/                    ← cole TUDO daqui num gist público
│   ├── hub.json
│   ├── leitor-conforto.user.js
│   ├── voltar-ao-topo.user.js
│   └── modo-noturno.user.js
└── README.md
```

## Testes / CI

Todo push dispara o workflow [`test.yml`](../.github/workflows/test.yml) (Node 20 e 22),
que verde somente se passar nas 4 etapas:

1. **Sintaxe** — `node --check` em todos os userscripts;
2. **Estática de completude** — metadados, `@grant`/`@connect` ↔ URLs usadas,
   `data-act` ↔ handlers, IDs ↔ templates, `hub.json` ↔ arquivos do gist, README ↔ código;
3. **Suíte funcional** (jsdom) — boot, abas, catálogo via gist, instalar, ⬆ update,
   copiar, busca/IME, tema, A+/A−, persistência, multi-página;
4. **Casos-limite S1–S8** (jsdom) — offline, gist sem `hub.json`, JSON quebrado,
   catálogo vazio, fonte sem resolução, ocultar/mostrar botão, 403 com cache, injeção dupla.

Local: `npm ci && npm test` · orquestração BPMN de pendências: `node scripts/orchestrator.mjs self-test` (workflows `orchestrate` + `guardian`).

Relatório formal de entrega (solicitado × implementado × testado × gaps): [`docs/ENTREGA.md`](../docs/ENTREGA.md).

Licença MIT.
