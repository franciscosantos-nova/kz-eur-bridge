"""Página de demonstração do kz-eur-bridge: uma família em Angola paga em
kwanzas e o saldo fica em euros (EURC), à taxa oficial mais uma margem
transparente. A página só lê a blockchain, nunca envia transações.
"""

from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation

import reflex as rx

from app.blockchain import (
    BASESCAN_ADDRESS_URL,
    EURC_ADDRESS,
    InvalidAmountError,
    ORACLE_ADDRESS,
    RpcConnectionError,
    StaleRateError,
    VAULT_ADDRESS,
    format_kz,
    get_quote,
    get_vault_snapshot,
    humanize_seconds_ago,
    parse_kz_input,
)

GITHUB_URL = "https://github.com/franciscosantos-nova/kz-eur-bridge"

DEFAULT_TRADITIONAL_FEE_EUR = "15"
DEFAULT_TRADITIONAL_MARKUP_PCT = "5"


class State(rx.State):
    """Estado da página: o formulário de cotação e o painel do cofre."""

    # ---- Formulário de cotação ----
    kz_input: str = "50000"
    traditional_fee_eur: str = DEFAULT_TRADITIONAL_FEE_EUR
    traditional_markup_pct: str = DEFAULT_TRADITIONAL_MARKUP_PCT

    quote_error: str = ""
    liquidity_warning: str = ""
    has_quote: bool = False
    quote_kz_str: str = ""
    quote_gross_str: str = ""
    quote_fee_str: str = ""
    quote_net_str: str = ""

    bridge_cost_pct_str: str = ""
    bridge_bar_width_str: str = "0%"
    traditional_cost_str: str = ""
    traditional_cost_pct_str: str = ""
    traditional_bar_width_str: str = "0%"
    traditional_fee_too_high: bool = False

    # ---- Painel "o cofre ao vivo" ----
    vault_error: str = ""
    vault_loaded: bool = False
    available_liquidity_str: str = ""
    total_liabilities_str: str = ""
    total_fees_collected_str: str = ""
    spread_pct_str: str = ""
    max_spread_pct_str: str = ""
    rate_is_stale: bool = False
    current_rate_str: str = ""
    rate_updated_ago_str: str = ""

    @rx.event
    def set_kz_input(self, value: str) -> None:
        self.kz_input = value

    @rx.event
    def set_traditional_markup_pct(self, value: str) -> None:
        self.traditional_markup_pct = value

    @rx.event
    def set_traditional_fee_eur(self, value: str) -> None:
        self.traditional_fee_eur = value

    @rx.event
    def calcular(self) -> None:
        self.quote_error = ""
        self.liquidity_warning = ""
        self.has_quote = False
        try:
            aoa_cents = parse_kz_input(self.kz_input)
            quote = get_quote(aoa_cents)
        except InvalidAmountError as exc:
            self.quote_error = str(exc)
            return
        except StaleRateError:
            self.quote_error = (
                "Taxa desatualizada: o oráculo precisa de ser atualizado antes de poder "
                "calcular uma cotação."
            )
            return
        except RpcConnectionError:
            self.quote_error = "Não foi possível ligar à rede Base Sepolia. Tenta novamente."
            return

        self.quote_kz_str = format_kz(aoa_cents)
        self.quote_gross_str = quote.gross_str
        self.quote_fee_str = quote.fee_str
        self.quote_net_str = quote.net_str
        self.has_quote = True
        if not quote.has_sufficient_liquidity:
            self.liquidity_warning = (
                "O cofre não tem liquidez suficiente para este montante neste momento "
                f"(máximo: {quote.max_kz_str})."
            )
        self._calcular_comparacao(quote.gross_micro, quote.fee_micro)

    def _calcular_comparacao(self, gross_micro: int, fee_micro: int) -> None:
        """Estimativa ilustrativa vs. um envio tradicional (comissão fixa + margem cambial).

        Ambos os custos são expressos em percentagem do valor à taxa oficial
        (o "valor enviado"), para serem comparáveis independentemente do montante.
        As barras mostram a mesma percentagem normalizada à maior das duas,
        porque o envio tradicional pode passar dos 100% em montantes pequenos.
        """
        try:
            fee_eur = Decimal(self.traditional_fee_eur.strip().replace(",", "."))
        except (InvalidOperation, ValueError):
            fee_eur = Decimal(DEFAULT_TRADITIONAL_FEE_EUR)
        try:
            markup_pct = Decimal(self.traditional_markup_pct.strip().replace(",", "."))
        except (InvalidOperation, ValueError):
            markup_pct = Decimal(DEFAULT_TRADITIONAL_MARKUP_PCT)

        gross_eur = Decimal(gross_micro) / Decimal(1_000_000)
        bridge_fee_eur = Decimal(fee_micro) / Decimal(1_000_000)
        traditional_cost_eur = fee_eur + gross_eur * (markup_pct / 100)

        self.traditional_fee_too_high = fee_eur > gross_eur

        if gross_eur > 0:
            bridge_pct = bridge_fee_eur / gross_eur * 100
            traditional_pct = traditional_cost_eur / gross_eur * 100
        else:
            bridge_pct = Decimal(0)
            traditional_pct = Decimal(0)

        max_pct = max(bridge_pct, traditional_pct)
        if max_pct > 0:
            bridge_bar_width = bridge_pct / max_pct * 100
            traditional_bar_width = traditional_pct / max_pct * 100
        else:
            bridge_bar_width = Decimal(0)
            traditional_bar_width = Decimal(0)

        self.bridge_cost_pct_str = f"{bridge_pct:.2f}".replace(".", ",") + "%"
        self.bridge_bar_width_str = f"{bridge_bar_width:.2f}%"
        self.traditional_cost_str = f"{traditional_cost_eur:.2f}".replace(".", ",") + " €"
        self.traditional_cost_pct_str = f"{traditional_pct:.2f}".replace(".", ",") + "%"
        self.traditional_bar_width_str = f"{traditional_bar_width:.2f}%"

    @rx.event
    def atualizar_cofre(self) -> None:
        self.vault_error = ""
        try:
            snapshot = get_vault_snapshot()
        except RpcConnectionError:
            self.vault_error = "Não foi possível ligar à rede Base Sepolia. Tenta novamente."
            return

        self.vault_loaded = True
        self.available_liquidity_str = snapshot.available_liquidity_str
        self.total_liabilities_str = snapshot.total_liabilities_str
        self.total_fees_collected_str = snapshot.total_fees_collected_str
        self.spread_pct_str = snapshot.spread_pct_str
        self.max_spread_pct_str = snapshot.max_spread_pct_str
        self.rate_is_stale = snapshot.rate_is_stale
        if snapshot.rate_is_stale:
            self.current_rate_str = ""
            self.rate_updated_ago_str = ""
        else:
            self.current_rate_str = snapshot.current_rate_str or ""
            seconds_ago = int(time.time()) - snapshot.oracle_updated_at
            self.rate_updated_ago_str = humanize_seconds_ago(seconds_ago)


# ---------------------------------------------------------------------------
# Estilo: tipografia, tema de cor e tokens reutilizados nos componentes.
# ---------------------------------------------------------------------------

FONT_STYLESHEET = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
FONT_FAMILY = "Inter, system-ui, sans-serif"

CARD_PROPS = {
    "size": "3",
    "width": "100%",
    "variant": "surface",
}


def _muted(*children, **props) -> rx.Component:
    props.setdefault("color", rx.color("gray", 10))
    return rx.text(*children, **props)


# ---------------------------------------------------------------------------
# 1. Topo
# ---------------------------------------------------------------------------


def _header() -> rx.Component:
    return rx.hstack(
        rx.hstack(
            rx.icon("waves", size=20, color=rx.color("jade", 9)),
            rx.text("kz-eur-bridge", weight="bold", size="4"),
            spacing="2",
            align="center",
        ),
        rx.spacer(),
        rx.hstack(
            rx.box(
                width="8px",
                height="8px",
                border_radius="50%",
                background=rx.color("jade", 9),
                box_shadow=f"0 0 0 3px {rx.color('jade', 4)}",
            ),
            _muted("Ao vivo na Base Sepolia", size="2"),
            rx.color_mode.button(),
            spacing="3",
            align="center",
        ),
        width="100%",
        padding_y="1.25em",
        align="center",
    )


# ---------------------------------------------------------------------------
# 2. Hero
# ---------------------------------------------------------------------------


def _hero() -> rx.Component:
    return rx.vstack(
        rx.heading(
            "Envia kwanzas. Recebe euros.",
            size="9",
            text_align="center",
            weight="bold",
        ),
        rx.text(
            "Uma família em Angola paga em kwanzas e o saldo fica em euros (EURC), "
            "à taxa oficial do BNA mais uma margem transparente — em vez de perder "
            "dinheiro em comissões bancárias e câmbios pouco claros.",
            size="4",
            color=rx.color("gray", 10),
            text_align="center",
            max_width="34em",
        ),
        spacing="4",
        align="center",
        width="100%",
        padding_y="1.5em",
    )


# ---------------------------------------------------------------------------
# 3. Cartão da cotação
# ---------------------------------------------------------------------------


def _quote_side(label: str, child: rx.Component) -> rx.Component:
    return rx.vstack(
        _muted(label, size="2", weight="medium"),
        child,
        align="start",
        spacing="1",
        width="100%",
    )


def _quote_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            _quote_side(
                "Pagas",
                rx.hstack(
                    rx.input(
                        value=State.kz_input,
                        on_change=State.set_kz_input,
                        placeholder="50000",
                        size="3",
                        variant="soft",
                        radius="large",
                        width="100%",
                        flex="1",
                    ),
                    rx.text("kz", size="5", weight="bold", color=rx.color("gray", 10)),
                    width="100%",
                    align="center",
                    spacing="2",
                ),
            ),
            rx.center(
                rx.icon("arrow-down", size=18, color=rx.color("gray", 8)),
                width="100%",
            ),
            _quote_side(
                "Recebes",
                rx.cond(
                    State.has_quote,
                    rx.heading(
                        State.quote_net_str,
                        size="9",
                        color=rx.color("jade", 11),
                        white_space="nowrap",
                    ),
                    rx.vstack(
                        rx.heading("0,00 €", size="9", color=rx.color("gray", 7)),
                        _muted("Escreve um montante e carrega em Calcular.", size="2"),
                        spacing="1",
                        align="start",
                    ),
                ),
            ),
            rx.button(
                "Calcular",
                on_click=State.calcular,
                size="3",
                width="100%",
                color_scheme="jade",
                radius="large",
            ),
            rx.cond(
                State.quote_error != "",
                rx.callout.root(
                    rx.callout.icon(rx.icon("triangle-alert")),
                    rx.callout.text(State.quote_error),
                    color_scheme="red",
                    variant="soft",
                    width="100%",
                ),
            ),
            rx.cond(
                State.has_quote,
                rx.vstack(
                    rx.cond(
                        State.liquidity_warning != "",
                        rx.callout.root(
                            rx.callout.icon(rx.icon("triangle-alert")),
                            rx.callout.text(State.liquidity_warning),
                            color_scheme="amber",
                            variant="soft",
                            width="100%",
                        ),
                    ),
                    rx.divider(),
                    _muted(
                        "À taxa oficial: "
                        + State.quote_gross_str
                        + "  ·  Margem: "
                        + State.quote_fee_str,
                        size="2",
                    ),
                    width="100%",
                    spacing="3",
                ),
            ),
            spacing="4",
            width="100%",
        ),
        **CARD_PROPS,
    )


# ---------------------------------------------------------------------------
# 4. Comparação de custos (barras)
# ---------------------------------------------------------------------------


def _cost_bar(label: str, pct_str: rx.Var, width_str: rx.Var, color: str) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(label, size="2", weight="medium"),
            rx.spacer(),
            rx.text(pct_str, size="2", weight="bold"),
            width="100%",
        ),
        rx.box(
            rx.box(
                width=width_str,
                height="100%",
                background=color,
                border_radius="999px",
                transition="width 0.3s ease",
            ),
            width="100%",
            height="10px",
            background=rx.color("gray", 4),
            border_radius="999px",
            overflow="hidden",
        ),
        spacing="1",
        width="100%",
    )


def _assumptions_accordion() -> rx.Component:
    return rx.accordion.root(
        rx.accordion.item(
            header="Ajustar pressupostos",
            content=rx.vstack(
                rx.hstack(
                    _muted("Comissão fixa do envio tradicional (€)", size="2"),
                    rx.spacer(),
                    rx.input(
                        value=State.traditional_fee_eur,
                        on_change=State.set_traditional_fee_eur,
                        width="90px",
                        size="2",
                    ),
                    width="100%",
                    align="center",
                ),
                rx.hstack(
                    _muted("Margem cambial do envio tradicional (%)", size="2"),
                    rx.spacer(),
                    rx.input(
                        value=State.traditional_markup_pct,
                        on_change=State.set_traditional_markup_pct,
                        width="90px",
                        size="2",
                    ),
                    width="100%",
                    align="center",
                ),
                rx.button("Recalcular", on_click=State.calcular, variant="outline", size="2"),
                spacing="3",
                padding_top="0.75em",
                width="100%",
            ),
            value="assumptions",
        ),
        collapsible=True,
        width="100%",
        variant="ghost",
    )


def _comparison_card() -> rx.Component:
    return rx.cond(
        State.has_quote,
        rx.card(
            rx.vstack(
                rx.heading("Comparação de custos", size="5"),
                _muted(
                    "Estimativa ilustrativa, em percentagem do valor enviado à taxa oficial.",
                    size="2",
                ),
                _cost_bar(
                    "kz-eur-bridge",
                    State.bridge_cost_pct_str,
                    State.bridge_bar_width_str,
                    rx.color("jade", 9),
                ),
                _cost_bar(
                    "Envio tradicional",
                    State.traditional_cost_pct_str,
                    State.traditional_bar_width_str,
                    rx.color("gray", 8),
                ),
                rx.cond(
                    State.traditional_fee_too_high,
                    rx.callout.root(
                        rx.callout.icon(rx.icon("info")),
                        rx.callout.text(
                            "Para montantes tão pequenos, um envio tradicional com esta "
                            "comissão fixa nem costuma ser usado na prática."
                        ),
                        color_scheme="gray",
                        variant="soft",
                        width="100%",
                    ),
                ),
                _assumptions_accordion(),
                spacing="4",
                width="100%",
            ),
            **CARD_PROPS,
        ),
    )


# ---------------------------------------------------------------------------
# 5. Como funciona
# ---------------------------------------------------------------------------


def _step_card(icon_name: str, title: str, text: str) -> rx.Component:
    return rx.vstack(
        rx.box(
            rx.icon(icon_name, size=22, color=rx.color("jade", 9)),
            padding="0.75em",
            background=rx.color("jade", 3),
            border_radius="999px",
        ),
        rx.text(title, weight="bold", size="3"),
        _muted(text, size="2", text_align="center"),
        align="center",
        spacing="2",
        width="100%",
        padding="1em",
    )


def _how_it_works() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Como funciona", size="5"),
            rx.grid(
                _step_card(
                    "smartphone",
                    "1. Pagas em kwanzas",
                    "Através de um canal local, como o Multicaixa.",
                ),
                _step_card(
                    "coins",
                    "2. Fica em euros",
                    "O saldo é convertido para EURC, à taxa oficial mais uma margem transparente.",
                ),
                _step_card(
                    "send",
                    "3. Usas ou envias",
                    "Pagas com cartão em Portugal, ou envias para a família, sem custos extra.",
                ),
                columns=rx.breakpoints(initial="1", sm="3"),
                spacing="2",
                width="100%",
            ),
            spacing="4",
            width="100%",
        ),
        **CARD_PROPS,
    )


# ---------------------------------------------------------------------------
# 6. O cofre ao vivo
# ---------------------------------------------------------------------------


def _metric_card(label: str, value: rx.Var) -> rx.Component:
    return rx.box(
        rx.vstack(
            _muted(label, size="2"),
            rx.text(value, size="5", weight="bold"),
            align="start",
            spacing="1",
        ),
        padding="1em",
        background=rx.color("gray", 2),
        border_radius="0.75em",
        width="100%",
    )


def _vault_panel() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading("O cofre ao vivo", size="5"),
                rx.spacer(),
                rx.button(
                    rx.icon("refresh-cw", size=16),
                    "Atualizar",
                    on_click=State.atualizar_cofre,
                    variant="soft",
                    size="2",
                ),
                width="100%",
                align="center",
            ),
            rx.cond(
                State.vault_error != "",
                rx.callout.root(
                    rx.callout.icon(rx.icon("triangle-alert")),
                    rx.callout.text(State.vault_error),
                    color_scheme="red",
                    variant="soft",
                    width="100%",
                ),
            ),
            rx.cond(
                State.vault_loaded,
                rx.vstack(
                    rx.grid(
                        _metric_card("Liquidez disponível", State.available_liquidity_str),
                        _metric_card("Total devido aos clientes", State.total_liabilities_str),
                        _metric_card("Margens recolhidas", State.total_fees_collected_str),
                        _metric_card(
                            "Margem atual / máxima",
                            State.spread_pct_str + "% / " + State.max_spread_pct_str + "%",
                        ),
                        columns=rx.breakpoints(initial="2", sm="4"),
                        spacing="3",
                        width="100%",
                    ),
                    rx.cond(
                        State.rate_is_stale,
                        rx.callout.root(
                            rx.callout.icon(rx.icon("triangle-alert")),
                            rx.callout.text(
                                "Taxa desatualizada: o oráculo precisa de ser atualizado."
                            ),
                            color_scheme="amber",
                            variant="soft",
                            width="100%",
                        ),
                        _metric_card(
                            "Taxa (AOA/EUR) e frescura",
                            State.current_rate_str + " · atualizada " + State.rate_updated_ago_str,
                        ),
                    ),
                    spacing="3",
                    width="100%",
                ),
            ),
            spacing="4",
            width="100%",
        ),
        **CARD_PROPS,
    )


# ---------------------------------------------------------------------------
# 7. Rodapé
# ---------------------------------------------------------------------------


def _link_contrato(nome: str, endereco: str) -> rx.Component:
    return rx.link(
        f"{nome} ({endereco[:6]}…{endereco[-4:]})",
        href=f"{BASESCAN_ADDRESS_URL}{endereco}#code",
        is_external=True,
        size="2",
        color=rx.color("gray", 10),
    )


def _footer() -> rx.Component:
    return rx.vstack(
        rx.divider(),
        rx.flex(
            _link_contrato("EuroVault", VAULT_ADDRESS),
            _link_contrato("EurAoaOracle", ORACLE_ADDRESS),
            _link_contrato("EURC (Circle)", EURC_ADDRESS),
            rx.link(
                "Código-fonte no GitHub",
                href=GITHUB_URL,
                is_external=True,
                size="2",
                color=rx.color("gray", 10),
            ),
            spacing="4",
            wrap="wrap",
            justify="center",
            width="100%",
        ),
        _muted(
            "Protótipo em testnet, construído como projeto de aprendizagem e portfólio. "
            "Não auditado. Não é para fundos reais.",
            size="1",
            text_align="center",
        ),
        spacing="4",
        align="center",
        width="100%",
        padding_y="2em",
    )


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------


def index() -> rx.Component:
    return rx.box(
        rx.box(
            rx.vstack(
                _header(),
                _hero(),
                rx.flex(
                    rx.vstack(
                        _quote_card(),
                        _comparison_card(),
                        spacing="4",
                        width="100%",
                        flex=rx.breakpoints(initial="1", lg="3"),
                    ),
                    rx.box(
                        _how_it_works(),
                        width="100%",
                        flex=rx.breakpoints(initial="1", lg="2"),
                    ),
                    direction=rx.breakpoints(initial="column", lg="row"),
                    spacing="4",
                    width="100%",
                    align="start",
                ),
                _vault_panel(),
                _footer(),
                spacing="5",
                width="100%",
                padding_y="1em",
            ),
            max_width="1100px",
            width="100%",
            margin="0 auto",
            padding_x="1.25em",
        ),
        min_height="100vh",
        width="100%",
        background=rx.color("gray", 1),
    )


app = rx.App(
    style={"font_family": FONT_FAMILY},
    stylesheets=[FONT_STYLESHEET],
)
app.add_page(index, on_load=State.atualizar_cofre)
