# FU_2 — Follow-up de Compras (modularizado)

Esta versão organiza a aplicação em camadas claras (core / services / ui / utils) e reduz a lógica “colada” no `app_refatorado.py`.

## Estrutura

- `app_refatorado.py`: ponto de entrada (Streamlit). Faz apenas:
  - configuração da página
  - verificação de autenticação
  - chamada do roteador + sidebar (componentes)
- `src/core/`: configuração, autenticação, database e modelos (Pydantic)
- `src/services/`: regras de negócio (ex.: pedidos)
- `src/ui/`
  - `pages/`: telas (dashboard, login, gestão de pedidos)
  - `components/`: componentes reutilizáveis (sidebar, etc.)
  - `router.py`: mapeamento de menu -> função de página
- `src/utils/`: utilitários (formatadores, etc.)

## Dependência importante (Pydantic EmailStr)

Os modelos usam `EmailStr` do Pydantic, que depende do pacote `email-validator`.
Por isso foi adicionado no `requirements-dev.txt`.

## Como rodar

```bash
pip install -r requirements-dev.txt
streamlit run app_refatorado.py
```

## Próximos passos sugeridos

- Criar páginas para: Upload em Massa, Mapa, Relatórios, Configurações (stubs já previstos no menu/roteador).
- Extrair componentes visuais do dashboard (cards, gráficos) para `src/ui/components/`.
- Centralizar tratamento de erros (ex.: exceptions -> `st.error` + logging).
