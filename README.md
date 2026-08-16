# mullid

Lokalne, trwałe tożsamości wyjściowe Mullvad. Jeden tunel WireGuard żyjący
w przestrzeni użytkownika daje tyle równoległych adresów wyjściowych, ile
profili — bez interfejsu `utun`, bez `sudo` i bez dotykania routingu
systemowego, więc ruch, którego nie skierowałeś jawnie na proxy, idzie do
sieci tak jak dotąd.

## Uruchomienie

```bash
python3 setup.py     # jednorazowo: rejestruje klucz, pobiera relaye i wireproxy
python3 -m mullid    # startuje tunel, proxy :8888 i control API :8889
```

## Użycie

Nazwa profilu jedzie jako użytkownik w uwierzytelnieniu proxy. Hasło jest
ignorowane i istnieje tylko dlatego, że klienci HTTP wymagają obu pól.

```bash
curl -x http://alice:x@127.0.0.1:8888 https://am.i.mullvad.net/json
```

| Nazwa | Znaczenie |
|---|---|
| `alice` | trwały; relay dobierany raz i zapamiętywany na stałe |
| `alice-de` | trwały, przypięty do Niemiec |
| `random` | świeże losowe wyjście przy każdym żądaniu, nic nie zapisywane |
| `random-jp` | jak wyżej, ograniczone do Japonii |

Sufiks kraju to dwuliterowy kod ISO. Nowy profil tworzy się sam — wystarczy
użyć nowej nazwy, nic nie trzeba wcześniej rejestrować.

Trwałość oznacza trwałość: przypisanie leży w `~/.mullid/state.json`, więc
profil dostaje ten sam adres wyjściowy po restarcie procesu i po restarcie
maszyny.

## Control API

| Trasa | Działanie |
|---|---|
| `GET /profiles` | profile z krajem, relayem i czasem ostatniego użycia |
| `POST /profiles/<name>/rotate` | porzuca dotychczasowy relay, przydziela nowy |
| `GET /health` | stan wireproxy, osiągalność SOCKS5, adres bezpośredni |

```bash
curl -s http://127.0.0.1:8889/profiles
curl -s -X POST http://127.0.0.1:8889/profiles/alice/rotate
```

`direct_ip` w `/health` to adres widziany **bez** tunelu. Ma pokazywać twój
adres domowy — to kontrola szczelności dowodząca, że routing systemowy jest
nietknięty.

## Jak to działa

Mullvad wystawia na każdym serwerze WireGuard proxy SOCKS5 na porcie 1080,
osiągalne wyłącznie z wnętrza sieci tunelowej, i proxy jednego serwera jest
dostępne z poziomu każdego innego. Na tym stoi całość.

```
klient  --HTTP proxy-->  mullid :8888  --socks5-->  wireproxy :1080
                              |                     (userspace WG, jeden tunel)
                              |                          |
                         state.json              --socks5--> nl-ams-wg-socks5-001:1080 -> wyjście NL
                      (profil -> relay)          --socks5--> se-sto-wg-socks5-007:1080 -> wyjście SE
```

Nazwa hosta docelowego przekazywana jest dalej jako domena i nie jest
rozwiązywana lokalnie — inaczej zapytanie DNS wyszłoby poza tunel i zdradziło
cel połączenia mimo poprawnie działającego proxy.

## Wdrożenie w kontenerze

Na Apple silicon, pod natywnym `container`. Obraz jest linuksowy i ciągnie
własną binarkę wireproxy — ta z `~/.mullid/bin/` jest zbudowana pod darwina
i w kontenerze bezużyteczna, dlatego ścieżkę nadpisuje `MULLID_WIREPROXY_BIN`.

```bash
python3 setup.py        # najpierw na hoście: rejestruje klucz
./container-deploy.sh   # buduje obraz i (re)startuje kontener
```

`setup.py` zostaje na hoście, bo woła `mullvad account get` i `openssl`.
Kontener dostaje gotowy `~/.mullid` jako wolumen — razem z `state.json`,
więc przypisania profili przeżywają przebudowę obrazu i restart kontenera.

Kontener nie potrzebuje żadnych uprawnień specjalnych: wireproxy działa
w całości w przestrzeni użytkownika, więc ani `/dev/net/tun`, ani `NET_ADMIN`,
ani trybu uprzywilejowanego.

### Zmienne środowiskowe

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `MULLID_BIND` | `127.0.0.1` | adres nasłuchu proxy i control API |
| `MULLID_WIREPROXY_BIN` | `~/.mullid/bin/wireproxy` | ścieżka do binarki wireproxy |
| `MULLID_HOME` | `~/.mullid` | katalog stanu |

Pusta wartość `MULLID_BIND` traktowana jest jak brak — literówka w skrypcie
wdrożeniowym daje bezpieczny domyślny nasłuch na pętli zwrotnej, a nie na
wszystkim.

### Autostart

`com.fran.mullid-container.plist` w `~/Library/LaunchAgents/` startuje
`container system start` i `container start mullid` przy logowaniu.

### Ostrzeżenie o wystawieniu

`container-deploy.sh` publikuje porty na `0.0.0.0`, czyli na całą sieć
lokalną. **Proxy nie sprawdza hasła** — pole hasła istnieje tylko dlatego,
że wymagają go klienci HTTP, a nazwa profilu to pole użytkownika. Każdy,
kto sięgnie tego portu, wyjdzie na cudzym koncie Mullvad, tworząc sobie
dowolny profil samą nazwą. Jest to świadomy wybór właściciela tej instalacji,
sensowny wyłącznie w zaufanej sieci. Żeby ograniczyć dostęp do samego hosta,
zmień publikację na `127.0.0.1:8888:8888` i sięgaj z zewnątrz tunelem SSH.

## Testy

```bash
python3 -m unittest discover -s tests -t .
```

Cały zestaw działa offline, na własnej atrapie serwera SOCKS5 — nie wymaga
tunelu ani konta.

## O czym trzeba pamiętać

**Adresy wyjściowe Mullvada nie są „świeże".** To współdzielone adresy
serwerowni, obecne na listach blokad większości systemów antybotowych.
Narzędzie nadaje się do rozdzielania profili, wyboru kraju i prywatności.
Nie nadaje się do udawania zwykłego użytkownika domowego — do tego służą
proxy residential.

**Nie kieruj przez to Claude.** Sens tej konstrukcji polega na nietykaniu
routingu systemowego; właśnie dlatego Claude działa, gdy mullid chodzi.
Ustawienie `HTTPS_PROXY` na `:8888` globalnie przywraca błąd 502, przed
którym to narzędzie ma chronić.

**Sekrety.** `~/.mullid/wg.conf` zawiera klucz prywatny WireGuard i ma
uprawnienia `600`. Nie jest nigdzie wypisywany ani logowany; pilnują tego
testy w `tests/test_device.py` i `tests/test_control.py`.

## Poza zakresem

SOCKS5 od strony klienta (samo `CONNECT` po HTTP pokrywa curl, przeglądarki
i biblioteki HTTP) oraz autostart przez launchd.
