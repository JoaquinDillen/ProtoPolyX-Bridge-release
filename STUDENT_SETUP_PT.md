# Guia de Configuracao para Estudantes

Este guia coloca um computador de estudante a correr a configuracao de sala de
aula entre PolyScope X e ProtoTwin.

Existem dois modos suportados:

```text
Modo Python bridge:
  URSim -> porta RTDE 30004 -> bridge.py/app.py -> ProtoTwin Connect

Modo Modbus direto:
  URSim Modbus TCP porta 502 -> ProtoTwin Connect -> URModbusJointMapper
```

Usa o modo Python bridge para jog manual em tempo real. Usa o modo Modbus direto
para executar programas normais no PolyScope e para controlar a garra atraves do
ProtoTwin Connect.

## 1. Instalar o software necessario

Instala o Docker Desktop:

```text
https://docs.docker.com/desktop/setup/install/windows-install/
```

Instala o ProtoTwin Connect:

```text
https://prototwin.com/account/signin
```

Os instaladores do ProtoTwin Connect ficam disponiveis na pagina da conta
ProtoTwin depois de iniciares sessao.

Instala Python 3.9 ou mais recente e depois instala os pacotes Python:

```powershell
pip install customtkinter ur-rtde prototwin
```

## 2. Usar os botoes de instalacao da app

A app inclui atalhos de instalacao na seccao Services:

```text
Docker Desktop      Install | Launch
ProtoTwin Connect   Install | Launch
```

O botao do Docker abre a pagina oficial de instalacao do Docker Desktop para
Windows. O botao do ProtoTwin abre a pagina de inicio de sessao do ProtoTwin,
onde os estudantes podem descarregar o ProtoTwin Connect a partir da conta.

## 3. Arrancar a app

A partir deste repositorio:

```powershell
python app.py
```

A app permite:

```text
1. Abrir o Docker Desktop.
2. Iniciar o contentor URSim PolyScope X.
3. Abrir o ProtoTwin Connect.
4. Abrir o PolyScope X no browser.
5. Abrir o ProtoTwin no browser.
6. Iniciar ou parar o Python bridge.
7. Controlar a garra do ProtoTwin por Bridge, Modbus ou Both.
```

## 4. Iniciar o URSim

Na app, clica:

```text
Docker Desktop -> Launch
URSim Container -> Launch
```

A app inicia o URSim com estas portas importantes:

```text
8000  interface web do PolyScope X
29999 dashboard server
30004 RTDE
502   Modbus TCP Server
```

As portas ficam ligadas apenas a `127.0.0.1`. Isto significa que o simulador de
cada estudante so fica acessivel no proprio computador e nao a partir de outras
maquinas da rede da sala.

Comando manual, se for necessario:

```powershell
docker run --rm --privileged --add-host host.docker.internal:host-gateway --env HOST_ARCH=amd64 --network bridge -p 127.0.0.1:8000:80 -p 127.0.0.1:29999:29999 -p 127.0.0.1:30004:30004 -p 127.0.0.1:502:502 universalrobots/ursim_polyscopex:latest
```

Verifica se o Modbus esta acessivel:

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 502
```

Resultado esperado:

```text
TcpTestSucceeded: True
```

## 5. Ativar servicos no PolyScope X

Abre o PolyScope X:

```text
http://localhost:8000
```

Em Settings / Services, ativa:

```text
Modbus TCP Server    Port 502
RTDE                 Port 30004
```

## 6. Preparar o ProtoTwin Connect para Modbus direto

No ProtoTwin Connect, adiciona um servidor Modbus:

```text
Protocol: Modbus/TCP
Type: Generic
Name: URSim
Host: 127.0.0.1
Port: 502
Unit ID: 255
Scan Rate: 0.02
```

Adiciona estas tags:

```text
Name         Type    Area              Address
J1_raw       UInt16  Holding Register  129
J2_raw       UInt16  Holding Register  130
J3_raw       UInt16  Holding Register  131
J4_raw       UInt16  Holding Register  132
J5_raw       UInt16  Holding Register  133
J6_raw       UInt16  Holding Register  134
Gripper_raw  UInt16  Holding Register  135
```

Para todas as tags:

```text
Access: Read
Masked write: Off
High word first: Default
```

## 7. Adicionar o mapper no ProtoTwin

No ProtoTwin, adiciona o componente com script:

```text
Prototwin Examples/URModbusJointMapper.ts
```

Liga as tags as entradas do mapper:

```text
J1_raw      -> URModbusJointMapper / Raw J 1
J2_raw      -> URModbusJointMapper / Raw J 2
J3_raw      -> URModbusJointMapper / Raw J 3
J4_raw      -> URModbusJointMapper / Raw J 4
J5_raw      -> URModbusJointMapper / Raw J 5
J6_raw      -> URModbusJointMapper / Raw J 6
Gripper_raw -> URModbusJointMapper / Raw Gripper
```

Cria ligacoes diretas de IO:

```text
Target J 1 -> A1 Target Position
Target J 2 -> A2 Target Position
Target J 3 -> A3 Target Position
Target J 4 -> A4 Target Position
Target J 5 -> A5 Target Position
Target J 6 -> A6 Target Position

Target Left Finger  -> Left Finger Target Position
Target Right Finger -> Right Finger Target Position
```

Se uma junta ou um dedo da garra se mover no sentido errado, altera a propriedade
de direcao correspondente no `URModbusJointMapper`.

## 8. Testar a comunicacao Modbus direta

No PolyScope X, executa isto uma vez:

```urscript
write_port_register(128, 12345)
```

Esperado no ProtoTwin:

```text
J1_raw = 12345
Raw J 1 = 12345
```

## 9. Usar os scripts de sala de aula

Atualizacao unica da posicao depois de jog manual:

```text
Prototwin Examples/update_prototwin_position_once.script
```

Sincronizacao continua das juntas durante um programa PolyScope:

```text
Prototwin Examples/modbus_joint_sync_thread.script
```

Teste de movimento finito:

```text
Prototwin Examples/modbus_joint_sync_move_test.script
```

Teste de abrir/fechar a garra:

```text
Prototwin Examples/set_prototwin_gripper.script
```

## 10. Comandos da garra a partir do PolyScope X

Usa estas funcoes num script PolyScope:

```urscript
def gripper_set_position(position):
  write_port_register(134, floor(position * 10000 + 0.5))
end

def gripper_open():
  gripper_set_position(0.0)
end

def gripper_close():
  gripper_set_position(0.4)
end
```

Exemplo:

```urscript
gripper_close()
sleep(1.0)
gripper_open()
```

## 11. Modo da garra na app

A seccao da garra na app tem um seletor de saida:

```text
Both
Bridge
Modbus
```

Usa:

```text
Both:
  Escreve em gripper_cmd.json e no registo Modbus 134.

Bridge:
  Usa apenas o caminho existente do Python bridge.

Modbus:
  Escreve apenas diretamente no registo Modbus 134.
```

## 12. Quando usar cada modo

Usa o modo Python bridge quando:

```text
Os estudantes fazem jog manual do robo e precisam de espelhamento em tempo real
no ProtoTwin.
```

Usa o modo Modbus direto quando:

```text
Os estudantes executam programas PolyScope e o ProtoTwin deve acompanhar.
Os estudantes precisam de comandos simples para abrir/fechar a garra a partir do PolyScope X.
Os estudantes fazem jog manual e depois executam "Update ProtoTwin Position" como checkpoint.
```

Mais detalhes tecnicos estao em:

```text
Prototwin Examples/Direct_Connection_Attempt.md
```
