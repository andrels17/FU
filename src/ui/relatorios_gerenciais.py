NameError: name 'df_base' is not defined

────────────────────── Traceback (most recent call last) ───────────────────────

  /home/adminuser/venv/lib/python3.11/site-packages/streamlit/runtime/scriptru  

  nner/script_runner.py:535 in _run_script                                      

                                                                                

  /mount/src/fu/app.py:45 in <module>                                           

                                                                                

      42 from src.ui.home import exibir_home                                    

      43 from src.core.superadmin import is_superadmin                          

      44 from src.ui.relatorios_whatsapp import render_relatorios_whatsapp      

  ❱   45 from src.ui.relatorios_gerenciais import render_relatorios_gerenciais  

      46                                                                        

      47 st.set_page_config(                                                    

      48 │   page_title="Sistema de Follow-Up",                                 

                                                                                

  /mount/src/fu/src/ui/relatorios_gerenciais.py:424 in <module>                 

                                                                                

    421 │                                                                       

    422 │   comparar = st.toggle("Comparar com período anterior", value=True,   

    423 │                                                                       

  ❱ 424 │   df_g = _safe_gastos_por_gestor(df_base, links, user_map)            

    425 │   if df_g is None or df_g.empty:                                      

    426 │   │   st.info("Sem dados para o agrupamento por Gestor (verifique ví  

    427 │   │   st.stop()                                                       

────────────────────────────────────────────────────────────────────────────────

NameError: name 'df_base' is not defined
