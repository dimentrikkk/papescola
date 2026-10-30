# Profitecla — acessos e assiduidade

Sistema para a **Escola Profissional Profitecla**: à entrada da escola (1.º andar), uma **porta com Raspberry Pi 4 + webcam + display + LEDs + buzzer + trinco** reconhece o aluno pela cara e regista a **entrada** (1.ª hora) e a **saída**. A partir daí o site calcula sozinho **presença, atraso ou falta**, avisa o aluno e o diretor de turma e **envia email ao encarregado de educação (EE)**.

> O horário das disciplinas já existe noutra aplicação da escola. Aqui só se define, por turma e dia, **a hora de entrada e a hora de saída**.

Evolução do projeto `betaPAP` (controlo de ponto): a base técnica (Flask + SQLite + `face_recognition`) mantém-se.

---

## 1. Como funciona

```
 ┌─────────────────────────── Raspberry Pi 4 ───────────────────────────┐
 │  Webcam USB ─► hardware/porteiro.py ──► flask_app/services/ ◄── site  │
 │                  (sem browser)            acesso_service      (gunicorn)
 │   Display I2C ◄──────┤                    presenca_service        ▲    │
 │   LED verde/verm. ◄──┤                    comunicacao_service     │    │
 │   Buzzer ◄───────────┤                           │                │    │
 │   Relé ► Trinco ◄────┤                           ▼                │    │
 │   Chave ► GPIO ──────┘                   SQLite (modo WAL) ───────┘    │
 └───────────────────────────────────────────────────────────────────────┘
        Alunos, professores e administração usam o site (rede da escola)
```

- O porteiro e o site partilham os mesmos serviços: as regras são iguais nos dois lados.
- O hardware está atrás de uma interface: `HARDWARE_MODO=mock` corre tudo no PC (o display aparece na consola).
- **Só contam a 1.ª entrada e a última saída do dia** (o leitor está só na entrada da escola).

### Papéis
| Papel | Pode |
|---|---|
| **Administração** | Alunos (com email do EE), turmas e cursos, **horários de entrada/saída**, professores, ver acessos e presenças, corrigir marcações, justificações, estatísticas, CSV, emails aos EE, eventos da porta, registo manual de entrada |
| **Professor / diretor de turma** | Ver a assiduidade das turmas que dirige (dia a dia e últimos 30 dias), corrigir marcações, receber avisos de faltas |
| **Aluno** | Ver o dia de hoje, calendário mensal de assiduidade, horário de entrada/saída, as suas passagens, pedir justificações |

---

## 2. Regras: presente, atraso ou falta

Definidas por turma e dia da semana (*Administração → Horários de entrada/saída*), por exemplo segunda a sexta 08:30–16:30.

| Situação | Resultado | Aviso |
|---|---|---|
| 1.ª entrada até `hora de entrada + 5 min` (`TOLERANCIA_ATRASO_MIN`) | **Presente** | — |
| 1.ª entrada depois disso | **Atraso** (com os minutos) | aluno + **email ao EE** na hora |
| Sem entrada `30 min` (`FALTA_APOS_MIN`) depois da hora de entrada | **Falta** | aluno + diretor de turma + **email ao EE** |
| Falta com justificação aprovada | **Falta justificada** | sem email |
| Entrou só depois da hora de saída | Falta | — |
| Saiu mais de 5 min antes da hora de saída | regista *saída antecipada* | email ao EE só se `AVISAR_SAIDA_ANTECIPADA=true` |

- Se o aluno chegar **depois** de ter sido marcada a falta, passa a **atraso** e o EE recebe novo email.
- Se um professor/admin **corrigir** uma falta/atraso para presente, o EE recebe um email de correção.
- Uma marcação **manual** (professor/admin) nunca é sobrescrita pelo cálculo automático, e pode ser reposta a automático.
- **Nunca se enviam emails sobre dias que não sejam hoje** (recalcular o passado não incomoda ninguém).
- Alunos **sem consentimento biométrico** não são reconhecidos: a secretaria faz **registo manual** de entrada/saída e eles têm as mesmas presenças.
- Os emails vão para a fila e são enviados por SMTP (ver secção 5). Sem SMTP ficam guardados e visíveis em *Emails aos EE*.
- O cálculo corre ao registar a entrada, de 5 em 5 minutos no porteiro, ao abrir o dashboard/turma, e no botão “Recalcular”.

---

## 2b. Correr no PC (demonstração, sem hardware)

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install Flask numpy Pillow                           # suficiente para o site e para os testes
python -m scripts.seed_demo                              # dados FICTÍCIOS (opcional; ignora se já houver alunos)
python main.py                                           # http://localhost:5000
```

No primeiro arranque (base de dados nova) é criada a conta de administração e **a password temporária aparece na consola** (ou define `ADMIN_PASSWORD`). Será pedido para a alterar.
Demo: `professor1@escola.pt` / `Professor123` · `aluno1001@escola.pt` / `Aluno1234`.

**Simular a porta sem câmara:** `python -m hardware.porteiro --simular` e escrever o nº de processo (`1001`), `chave` ou `sair`.
**Com reconhecimento facial real no PC:** `pip install -r requirements.txt`, registar rostos em *Alunos → editar → Registar rosto* e abrir `http://localhost:5000/kiosk/`.

### Se já tinha uma versão anterior (horários por disciplina)
Basta correr a nova versão com a **mesma pasta `data/`**. Ao arrancar, a base de dados é **migrada automaticamente**: faz primeiro uma **cópia de segurança** (`data/escola.db.bak-v1-…`), mantém alunos, professores, turmas, rostos, acessos e notificações, converte os horários antigos em *entrada = 1.ª aula do dia* e *saída = fim da última aula*, e recalcula as presenças **sem enviar emails**.

---

## 3. Montagem do hardware

> ⚠️ **Antes de ligar:** desliga o Pi. Confirma os pinos com `pinout` no terminal. Os GPIO do Pi são de **3,3 V** e não suportam 5 V nem muita corrente.

### Ligações (numeração BCM, alteráveis no `.env`)

| Componente | Liga a | Pino físico | Notas |
|---|---|---|---|
| LED verde | GPIO17 → resistência 220 Ω → ânodo; cátodo → GND | 11 | |
| LED vermelho | GPIO27 → resistência 220 Ω → ânodo; cátodo → GND | 13 | |
| Buzzer | GPIO22 → `+`; `−` → GND | 15 | Se for **passivo** não toca só com ligar/desligar; use um **ativo**. Se consumir > 10 mA, use um transístor (BC547 + 1 kΩ na base) |
| Módulo relé | VCC → 5 V (pino 2), GND → GND (pino 6), **IN → GPIO23** | 16 | Confirme que aceita sinal de 3,3 V. Se ligar ao contrário, mude `RELE_ACTIVE_HIGH` |
| Switch com chave | um terminal → GPIO24, outro → GND | 18 | Pull-up interno (ligado = “porta livre”) |
| Display I2C | SDA → GPIO2 (pino 3), SCL → GPIO3 (pino 5), GND, VCC | 3, 5 | Ver nota abaixo |
| Webcam | USB | — | |
| Trinco | Fonte própria (normalmente 12 V) **através do contacto do relé** | — | Ver esquema abaixo |

### Trinco (a parte que exige cuidado)
```
 Fonte 12 V (+) ──► COM (relé)
                    NO  ──► Trinco (+)          ← trinco normal: abre quando o relé liga
 Fonte 12 V (−) ──────────► Trinco (−)
              Díodo 1N4007 em paralelo com o trinco (risca para o lado do +)
```
- **Nunca** alimentes o trinco pelo Pi. Usa uma fonte separada com a corrente do trinco.
- O díodo protege o relé da faísca quando a bobina do trinco desliga.
- **Segurança em edifício escolar:** se faltar a luz ou o Pi avariar, a porta **não pode** prender pessoas. Pergunta se o trinco é *fail-safe* (abre sem corrente). Nesse caso liga ao contacto **NC** e põe `TRINCO_MODO=energiza_para_trancar`. Garante sempre uma saída de emergência mecânica e usa o switch com chave como abertura manual.

### Display I2C
- Num **LCD de caracteres 16×2** (módulo com mochila PCF8574): `DISPLAY_TIPO=lcd`, endereço normalmente `0x27` ou `0x3F`.
- Num **OLED** (SSD1306): `DISPLAY_TIPO=oled`, endereço normalmente `0x3C`, e instala `luma.oled`.
- Descobre o endereço com `i2cdetect -y 1`.
- ⚠️ A mochila do LCD costuma ter *pull-ups* a 5 V nas linhas SDA/SCL. Muitos tutoriais ligam direto e funciona, mas tecnicamente o ideal é usar um **conversor de nível I2C**, ou retirar/desligar essas resistências, para proteger o Pi.
- O LCD não tem acentos: o programa remove-os automaticamente (“Ola Joao”).

---

## 4. Instalação no Raspberry Pi 4

1. **Sistema:** Raspberry Pi OS **64-bit**. Define o fuso horário (as horas dos acessos usam a hora do Pi):
   `sudo timedatectl set-timezone Europe/Lisbon`
2. **Ativar I2C e permissões:**
   ```bash
   sudo raspi-config nonint do_i2c 0
   sudo usermod -aG gpio,i2c,video $USER      # depois: terminar sessão e entrar de novo
   sudo apt update
   sudo apt install -y python3-venv python3-dev build-essential cmake libopenblas-dev liblapack-dev libjpeg-dev i2c-tools
   ```
3. **Swap (importante para compilar o dlib):** aumenta para 2 GB em `/etc/dphys-swapfile` (`CONF_SWAPSIZE=2048`) e `sudo systemctl restart dphys-swapfile`.
4. **Projeto:**
   ```bash
   cd ~/escola_acessos
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-pi.txt          # o dlib demora 20–60 minutos a compilar
   cp .env.example .env && nano .env           # HARDWARE_MODO=real, KIOSK_WEB_ENABLED=false, COOKIE_SECURE...
   ```
5. **Testar cada componente ANTES de tudo junto:**
   ```bash
   python -m hardware.teste_hardware leds
   python -m hardware.teste_hardware buzzer
   python -m hardware.teste_hardware display
   python -m hardware.teste_hardware rele      # 1.ª vez SEM o trinco ligado: ouvem-se dois cliques
   python -m hardware.teste_hardware chave
   python -m hardware.teste_hardware camara    # grava teste_camara.jpg
   ```
6. **Registar os rostos** (ver nota abaixo) e **arrancar como serviços** (sobrevivem a reinícios):
   ```bash
   sudo cp deploy/escola-web.service deploy/escola-porteiro.service /etc/systemd/system/
   sudo systemctl enable --now escola-web escola-porteiro
   journalctl -u escola-porteiro -f            # ver o que o porteiro está a fazer
   crontab -e                                  # colar deploy/crontab.example (emails + limpeza RGPD)
   ```

**Registar rostos:** os browsers só permitem a câmara em `localhost` ou **HTTPS**. Opções: (a) fazer o registo no próprio Pi, em `http://localhost:8000`; (b) usar o botão **“carregar fotografias”** da mesma página a partir de qualquer PC; (c) pôr o site atrás de HTTPS (nginx + certificado) e `COOKIE_SECURE=true`.

**Desempenho:** o `face_recognition` com HOG num Pi 4 demora aproximadamente meio segundo a um segundo por imagem; por isso o porteiro reduz a imagem (`FACE_SCALE=0.5`) e analisa uma imagem a cada ~0,4 s. Se estiver lento, baixa `CAMARA_LARGURA/ALTURA` (ex.: 480×360).

---

## 5. Configuração

Tudo em variáveis de ambiente (`.env.example` documenta cada uma). As principais:

| Variável | Por defeito | Efeito |
|---|---|---|
| `ESCOLA_NOME` / `ESCOLA_CONTACTO` | Escola Profissional Profitecla / — | Nome e contacto no site e na assinatura dos emails |
| `TOLERANCIA_ATRASO_MIN` | 5 | Minutos de tolerância após a hora de entrada |
| `FALTA_APOS_MIN` | 30 | Passado este tempo sem entrada → falta + email ao EE |
| `AVISAR_EE_ATRASO` / `AVISAR_EE_FALTA` | true / true | Ligar/desligar os emails |
| `AVISAR_SAIDA_ANTECIPADA` | false | Email ao EE quando o aluno sai mais cedo |
| `COOLDOWN_SEGUNDOS` | 30 | Impede alternar entrada/saída se o aluno ficar parado à frente da câmara |
| `FACE_TOLERANCE` / `FACE_MARGEM` | 0,5 / 0,04 | Rigor do reconhecimento; recusa-se quando dois alunos são parecidos |
| `GUARDAR_FOTOS_ACESSO` | false | Guardar foto em cada acesso (desligado por privacidade) |
| `TRINCO_MODO` | energiza_para_abrir | ou `energiza_para_trancar` (trinco fail-safe) |
| `HARDWARE_MODO` | mock | `real` no Raspberry Pi |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | — | Servidor de email. **Sem isto os avisos ficam na fila e não saem da escola** |

**Emails:** com `SMTP_HOST` definido, o porteiro envia a fila automaticamente de minuto a minuto (numa thread própria, para um servidor lento nunca atrasar a porta). Também há o botão *Enviar pendentes agora* e `python -m scripts.enviar_emails --loop`.

**Aspeto:** o logótipo está em `flask_app/static/logo-profitecla.svg` (e o ícone do separador em `favicon.svg`); cores e animações em `static/css/styles.css` (variáveis no topo, paleta do logótipo `#008ad8 · #3c9fe0 · #71b5e8`). O site respeita a opção “reduzir animações” do sistema.

---

## 7. Privacidade (RGPD) — a ter em conta

Isto **não é aconselhamento jurídico**; confirma com o encarregado de proteção de dados da escola.

- A biometria (rosto) é **dado de categoria especial** e os alunos são, na maioria, **menores**: é necessário **consentimento** (do encarregado de educação) e uma **alternativa** sem biometria. O sistema só permite registar rostos de alunos com consentimento registado e **apaga os dados biométricos quando o consentimento é retirado**.
- Guardam-se **vetores numéricos**, não fotografias. As fotos de acesso estão **desligadas** por defeito.
- Eventos da porta (incluindo rostos desconhecidos) são apagados ao fim de `RETENCAO_EVENTOS_DIAS` (`scripts/limpar_dados.py`).
- Apagar um aluno apaga **em cascata** os seus acessos, presenças e biometria.
- `data/` está no `.gitignore`: **nunca** publiques a base de dados nem fotos. A demo usa só dados fictícios.
- Uma avaliação de impacto (AIPD) é provavelmente exigível numa instalação real.

### Segurança aplicada
Passwords com hash (scrypt) · bloqueio após 5 tentativas · mudança de password obrigatória no 1.º login · proteção **CSRF** em todos os formulários · autorização por papel em cada rota · cada aluno só vê a sua própria foto · uploads revalidados e reguardados com PIL · queries parametrizadas · CSV com proteção contra injeção de fórmulas · cabeçalhos de segurança · segredo de sessão aleatório por instalação.

---

## 8. Testes

```bash
python -m unittest discover -s tests -t . -v      # 79 testes; não precisam de dlib nem de Raspberry Pi
```
Cobrem: regras de presença/atraso/falta, cooldown, alertas, justificações, prioridade do professor, reconhecimento (com um backend falso), consentimento, controlo de acesso por papel, CSRF, bloqueio de login, acesso a ficheiros, todas as páginas, e o porteiro com hardware simulado (incluindo trinco fail-safe e chave de emergência).

---

## 9. Limitações conhecidas e melhorias futuras

- **Sem prova de vida:** uma fotografia ou um vídeo no telemóvel pode enganar o reconhecimento. Mitigações simples: recusa quando dois alunos são parecidos (já feito) e vigilância; melhorias: câmara de profundidade/IR ou desafio (piscar de olhos).
- **Um aluno de cada vez:** não deteta *tailgating* (alguém a entrar atrás).
- **Falsas faltas:** se um aluno entrar sem passar pelo leitor (porta aberta com a chave, avaria), ao fim de `FALTA_APOS_MIN` o EE recebe um aviso de falta. O professor/administração corrige a marcação e o EE recebe automaticamente um email de correção — por isso convém registar as entradas manuais logo que possível.
- Como a porta só regista na entrada da escola, não se sabe se o aluno esteve presente em cada aula, apenas se esteve na escola.
- Só **alunos** são reconhecidos (professores e funcionários ainda não têm biometria nem acesso por rosto).
- O trinco e o display dependem da qualidade da alimentação; recomenda-se UPS/bateria e fonte de 5 V / 3 A.
- SQLite chega para uma escola com um só ponto de entrada; vários pontos → PostgreSQL.
- O Chart.js e os ícones vêm de CDN (precisa de internet nos browsers); para uso offline, copiar os ficheiros para `static/`.
- Envio de email precisa de SMTP; sem isso os avisos ficam na fila (vê-se no painel).
- Alternativa mais rápida ao dlib no Pi: modelos ONNX do OpenCV (SFace/YuNet).

---

## 10. Estrutura

```
main.py                     arranque do site
flask_app/
  config.py db.py security.py utils.py
  routes/   auth · kiosk(web, ensaio) · media · admin/ · professor · aluno
  services/ acesso_service   (entrada/saída, atraso, cooldown)
            presenca_service (presente/atraso/falta por dia, avisos, justificações)
            face_service     (identificação, consentimento, amostras)
            horario_service  (hora de entrada/saída por turma e dia)
            comunicacao_service (textos dos emails aos EE) · estatisticas_service
            notification_service (avisos + fila de emails) · auth_service
  templates/ static/
hardware/
  base.py mock.py real.py camera.py       interface + implementações
  porteiro.py                             o processo da porta (câmara → hardware)
  teste_hardware.py                       testa cada componente
scripts/    seed_demo · limpar_dados · enviar_emails
deploy/     serviços systemd + crontab
tests/      79 testes
```

---

## 11. Perguntas prováveis na defesa da PAP

- *Porque é que o porteiro é um processo separado do site?* Porque o Pi não tem ecrã (não há browser) e a porta tem de continuar a funcionar mesmo que o site esteja ocupado; partilham a lógica pelos mesmos serviços.
- *E se o display, a câmara ou a rede falharem?* O display avariado é ignorado (a porta funciona); a câmara tem retentativas e mostra erro; sem rede a porta funciona na mesma (tudo é local); um erro inesperado nunca abre a porta.
- *E se faltar a luz?* Depende do trinco: com trinco *fail-safe* (`energiza_para_trancar`) abre sozinho; além disso há o switch com chave.
- *Como evitas registar a pessoa errada?* Distância máxima, recusa de rostos ambíguos entre dois alunos, e impede-se o mesmo rosto em dois alunos ao registar.
- *E os alunos que não querem biometria?* Registo manual pela secretaria; têm as mesmas presenças e a mesma conta.
- *Como sabes que funciona?* 79 testes automáticos, incluindo o porteiro com hardware simulado.
