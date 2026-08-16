# mullid — lokalny menedżer tożsamości wyjściowych Mullvad

Data: 2026-08-16

## Problem

Włączenie Mullvada globalnie zrywa pracę z Claude — Anthropic odrzuca ruch
z adresów Mullvada błędem 502. Jednocześnie potrzebne są rozdzielne, trwałe
tożsamości sieciowe: kilka równoległych profili, z których każdy stale wychodzi
do internetu spod własnego adresu, plus możliwość doraźnego wypchnięcia
pojedynczego żądania przez inny kraj.

Te dwa wymagania są sprzeczne tylko pozornie. Sprzeczne są dopiero wtedy, gdy
tunel obsługuje cały system. Rozwiązaniem jest tunel, o którym system nie wie.

## Zasada działania

Mullvad wystawia na każdym serwerze WireGuard proxy SOCKS5 na porcie 1080,
osiągalne wyłącznie z wnętrza sieci tunelowej. Proxy jednego serwera jest
dostępne z poziomu każdego innego, co pozwala jednym tunelem wychodzić przez
dowolną liczbę serwerów naraz.

Na tym stoi całość: jeden tunel WireGuard żyjący w przestrzeni użytkownika,
a za nim tyle adresów wyjściowych, ile profili.

```
klient  --HTTP proxy-->  mullid :8888  --socks5-->  wireproxy :1080
                              |                     (userspace WG, jeden tunel)
                              |                          |
                         state.json              --socks5--> nl-ams-wg-socks5-001:1080 -> wyjście NL
                      (profil -> relay)          --socks5--> se-sto-wg-socks5-007:1080 -> wyjście SE
```

Routing systemowy pozostaje nietknięty. Nie powstaje interfejs `utun`, nie jest
potrzebny `sudo`, aplikacja Mullvada może być wyłączona. Ruch, którego nikt nie
skierował jawnie na `127.0.0.1:8888`, idzie do sieci tak jak dotąd — łącznie
z ruchem Claude.

## Środowisko

Ustalone pomiarem na maszynie docelowej, nie założone:

| Element | Stan |
|---|---|
| `mullvad` CLI | 2026.1, aplikacja zalogowana |
| Konto | aktywne, wolne sloty na urządzenia |
| Relaye WireGuard | 276 |
| Python | 3.14.6 |
| OpenSSL | 3.6.2, X25519 obecny (DER 48 B priv / 44 B pub) |
| `POST /auth/v1/token` | 200, zwraca `access_token` i `expiry` |
| Go, Docker, `wg` | brak — stąd gotowa binarka wireproxy |

## Klucz WireGuard

Klucz prywatny urządzenia zarejestrowanego w aplikacji Mullvada leży w jej
chronionym magazynie i nie da się go stamtąd wydobyć. `mullid` rejestruje więc
własne urządzenie, zajmując jeden z dwóch wolnych slotów.

Przebieg jednorazowego setupu:

1. `openssl genpkey -algorithm X25519` — para kluczy powstaje lokalnie; z DER
   brane są ostatnie 32 bajty i kodowane base64, jak wymaga WireGuard.
2. Numer konta odczytywany z `mullvad account get` w trakcie działania skryptu.
3. `POST /auth/v1/token` → token dostępowy.
4. `POST /accounts/v1/devices` z kluczem publicznym → adres tunelowy IPv4/IPv6.
5. Zapis do `~/.mullid/wg.conf`, uprawnienia `600`.

### Obchodzenie się z sekretami

Klucz prywatny, numer konta i token dostępowy nie trafiają nigdy na
standardowe wyjście, do logów ani do komunikatów o błędach. Skrypty czytają je
z pliku i przekazują dalej w pamięci. Diagnostyka posługuje się wyłącznie
metadanymi: obecnością pliku, jego uprawnieniami, długością wartości, kodem
odpowiedzi HTTP. Jest to twarde wymaganie, nie zalecenie — obowiązuje tak samo
kod, jak i wszelkie ręczne polecenia uruchamiane przy pracy nad projektem.

`.gitignore` obejmuje `*.conf`, `state.json` i cały `~/.mullid`.

## Składniki

### 1. `setup.py` — jednorazowa inicjalizacja

Rejestruje urządzenie wedle procedury wyżej. Pobiera
`https://api.mullvad.net/www/relays/wireguard/` i zapisuje `relays.json`.
Odpowiedź zawiera pole `socks_name` dla każdego relaya, na przykład
`nl-ams-wg-socks5-001.relays.mullvad.net` — dzięki temu adresy `10.124.x.y`
nie muszą być nigdzie wyliczane ani zgadywane.

Instaluje binarkę wireproxy v1.1.3 (darwin/arm64) z wydań GitHuba.

Przy 5 z 5 zajętych slotów kończy się czytelnym komunikatem wskazującym, że
trzeba zwolnić urządzenie na stronie Mullvada.

### 2. `wireproxy.conf` — generowany

Jedna sekcja `[Interface]` z kluczem i adresem tunelowym, jedna `[Peer]`
wskazująca relay wejściowy (wybierany blisko: `nl-ams` lub `de-fra`), jedna
`[Socks5]` nasłuchująca na `127.0.0.1:1080`.

Relay wejściowy służy wyłącznie za wjazd do sieci Mullvada. Adres wyjściowy
wybiera dopiero `mullid`, per profil.

### 3. `mullid.py` — proxy na `127.0.0.1:8888`

Proxy HTTP obsługujące `CONNECT` oraz żądania z absolutnym URI. Nazwa profilu
przyjeżdża jako użytkownik w nagłówku `Proxy-Authorization`; hasło jest
ignorowane i istnieje tylko dlatego, że klienci HTTP wymagają obu pól.

Gramatyka nazwy użytkownika:

| Nazwa | Znaczenie |
|---|---|
| `alice` | trwały; relay dobierany raz i zapamiętywany |
| `alice-de` | trwały, przypięty do Niemiec |
| `random` | świeże losowe wyjście przy każdym żądaniu, nic nie zapisywane |
| `random-jp` | jak wyżej, ograniczone do Japonii |

Sufiks kraju to dwuliterowy kod ISO zgodny z `country_code` z `relays.json`.
Nazwa profilu pasuje do `[a-z0-9_]+`; kod kraju odcinany jest od ostatniego
myślnika.

Obsługa pojedynczego żądania:

1. połączenie do wireproxy na `127.0.0.1:1080`,
2. `CONNECT` SOCKS5 do `<socks_name>:1080` wybranego relaya,
3. na uzyskanym strumieniu drugi `CONNECT` SOCKS5, tym razem do właściwego celu,
4. dwukierunkowe przepisywanie bajtów aż do zamknięcia.

Nazwa hosta docelowego przekazywana jest dalej jako domena i **nie jest
rozwiązywana lokalnie**. Rozwiązanie jej po stronie maszyny wypuściłoby
zapytanie DNS poza tunel i ujawniło cel połączenia mimo poprawnie działającego
proxy.

### 4. Control API — `127.0.0.1:8889`

| Trasa | Działanie |
|---|---|
| `GET /profiles` | profile z krajem, relayem, adresem wyjściowym i czasem ostatniego użycia |
| `POST /profiles/<name>/rotate` | porzuca dotychczasowy relay i przydziela nowy |
| `GET /health` | stan procesu wireproxy, świeżość handshake'u, widoczny adres wyjściowy |

Obie usługi wiążą się wyłącznie z pętlą zwrotną. Brak uwierzytelniania jest
świadomy: dostęp do `127.0.0.1` mają procesy tego użytkownika, a te i tak mogą
czytać `~/.mullid`.

## Stan

`~/.mullid/state.json`, zapis atomowy przez plik tymczasowy i `rename`.
Odwzorowanie `profil -> {relay, country, created, last_used, rotated_at}`.

Trwałość wynika stąd, że przypisanie jest wpisem w pliku, nie żywym
połączeniem — profil przeżywa restart procesu i restart maszyny.

## Błędy

Awarie mają być głośne. Ciche degradacje są w tym systemie groźniejsze niż
przerwa w działaniu, bo żądanie, które wyszło nie tym adresem co trzeba,
psuje dokładnie to, do czego służy narzędzie.

- wireproxy nie odpowiada albo handshake wygasł → `502` z treścią nazywającą
  przyczynę; żadnych zawieszeń bez odpowiedzi,
- relay niedostępny → profil dostaje nowy relay, a `/profiles` pokazuje
  `reassigned_at`, żeby złamanie trwałości było widoczne,
- brak lub błędna nazwa profilu → `407` z wyjaśnieniem składni.

## Testy

Jednostkowe: parser gramatyki nazw, wybór relaya (deterministyczny przy
ustalonym ziarnie i filtrze kraju), zapis i odczyt `state.json`.

Integracyjne: atrapa serwera SOCKS5 uruchamiana lokalnie, weryfikująca
poprawność bajtów łańcucha, powtarzalność relaya dla profilu trwałego po
restarcie procesu oraz zmianę relaya po `rotate`.

Dymne, na żywym tunelu:

```
curl -x http://alice:x@127.0.0.1:8888 https://am.i.mullvad.net/json
```

Dwa wywołania dla `alice` muszą zwrócić identyczny `mullvad_exit_ip_hostname`,
wywołanie dla innego profilu — inny.

## Poza zakresem

**SOCKS5 od strony klienta.** Samo `CONNECT` po HTTP pokrywa curl, przeglądarki
i biblioteki HTTP. Do dołożenia, jeśli pojawi się narzędzie, które tego wymaga.

**Autostart przez launchd.** Do rozważenia po potwierdzeniu, że całość działa.

## Ograniczenia, o których trzeba pamiętać

**Adresy wyjściowe Mullvada nie są „świeże".** To współdzielone adresy
serwerowni, obecne na listach blokad większości systemów antybotowych —
błąd 502 od Claude jest tego objawem. Narzędzie nadaje się do rozdzielania
profili, wyboru kraju i prywatności. Nie nadaje się do udawania zwykłego
użytkownika domowego; do tego służą proxy residential.

**Nie kierować przez to Claude.** Sens konstrukcji polega na nietykaniu
routingu systemowego. Ustawienie `HTTPS_PROXY` na `:8888` globalnie przywraca
pierwotny problem.
