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
    traditional_cost_str: str = ""
    traditional_cost_pct_str: str = ""
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

        self.bridge_cost_pct_str = f"{bridge_pct:.2f}".replace(".", ",") + "%"
        self.traditional_cost_str = f"{traditional_cost_eur:.2f}".replace(".", ",") + " €"
        self.traditional_cost_pct_str = f"{traditional_pct:.2f}".replace(".", ",") + "%"

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


def _link_contrato(nome: str, endereco: str) -> rx.Component:
    return rx.link(
        f"{nome} ({endereco[:6]}…{endereco[-4:]})",
        href=f"{BASESCAN_ADDRESS_URL}{endereco}#code",
        is_external=True,
    )


def _linha_painel(rotulo: str, valor: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.text(rotulo, color=rx.color("gray", 11)),
        rx.spacer(),
        rx.text(valor, font_weight="bold"),
        width="100%",
    )


def index() -> rx.Component:
    return rx.container(
        rx.color_mode.button(position="top-right"),
        rx.vstack(
            rx.heading("kz-eur-bridge", size="9"),
            rx.text(
                "Uma família em Angola paga em kwanzas e o saldo fica em euros (EURC), "
                "à taxa oficial do BNA mais uma margem transparente — em vez de perder "
                "dinheiro em comissões bancárias e câmbios pouco claros.",
                size="4",
                color=rx.color("gray", 11),
            ),
            rx.divider(),
            # ---- Cotação ----
            rx.heading("Calcular uma cotação", size="6"),
            rx.hstack(
                rx.input(
                    value=State.kz_input,
                    on_change=State.set_kz_input,
                    placeholder="Montante em kwanzas, ex: 50000",
                    width="100%",
                ),
                rx.button("Calcular", on_click=State.calcular),
                width="100%",
            ),
            rx.cond(
                State.quote_error != "",
                rx.callout(State.quote_error, icon="triangle_alert", color_scheme="red"),
            ),
            rx.cond(
                State.has_quote,
                rx.vstack(
                    _linha_painel("Montante pago (kz)", State.quote_kz_str),
                    _linha_painel("À taxa oficial", State.quote_gross_str),
                    _linha_painel("Margem cobrada", State.quote_fee_str),
                    _linha_painel("O cliente recebe", State.quote_net_str),
                    rx.cond(
                        State.liquidity_warning != "",
                        rx.callout(
                            State.liquidity_warning, icon="triangle_alert", color_scheme="amber"
                        ),
                    ),
                    rx.divider(),
                    rx.text(
                        "Comparação com um envio tradicional — estimativa ilustrativa, com "
                        "uma comissão fixa e uma margem cambial configuráveis, ambas típicas "
                        "deste tipo de serviço.",
                        size="2",
                        color=rx.color("gray", 11),
                    ),
                    rx.hstack(
                        rx.text("Comissão fixa (€)"),
                        rx.input(
                            value=State.traditional_fee_eur,
                            on_change=State.set_traditional_fee_eur,
                            width="80px",
                        ),
                        rx.text("Margem cambial (%)"),
                        rx.input(
                            value=State.traditional_markup_pct,
                            on_change=State.set_traditional_markup_pct,
                            width="80px",
                        ),
                        rx.button("Recalcular", on_click=State.calcular, variant="outline"),
                    ),
                    _linha_painel("Custo do kz-eur-bridge (% do valor enviado)", State.bridge_cost_pct_str),
                    _linha_painel(
                        "Custo do envio tradicional (% do valor enviado)",
                        State.traditional_cost_pct_str,
                    ),
                    _linha_painel("Custo estimado do envio tradicional (€)", State.traditional_cost_str),
                    rx.cond(
                        State.traditional_fee_too_high,
                        rx.callout(
                            "Para montantes tão pequenos, um envio tradicional com esta "
                            "comissão fixa nem costuma ser usado na prática.",
                            icon="info",
                            color_scheme="gray",
                        ),
                    ),
                    width="100%",
                    padding="1em",
                    border=f"1px solid {rx.color('gray', 6)}",
                    border_radius="0.75em",
                ),
            ),
            rx.divider(),
            # ---- Painel do cofre ----
            rx.hstack(
                rx.heading("O cofre ao vivo", size="6"),
                rx.spacer(),
                rx.button("Atualizar", on_click=State.atualizar_cofre, variant="outline"),
                width="100%",
                align="center",
            ),
            rx.cond(
                State.vault_error != "",
                rx.callout(State.vault_error, icon="triangle_alert", color_scheme="red"),
            ),
            rx.cond(
                State.vault_loaded,
                rx.vstack(
                    _linha_painel("Liquidez disponível", State.available_liquidity_str),
                    _linha_painel("Total devido aos clientes", State.total_liabilities_str),
                    _linha_painel("Margens recolhidas", State.total_fees_collected_str),
                    _linha_painel("Margem atual / máxima", State.spread_pct_str + "% / " + State.max_spread_pct_str + "%"),
                    rx.cond(
                        State.rate_is_stale,
                        rx.callout(
                            "Taxa desatualizada: o oráculo precisa de ser atualizado.",
                            icon="triangle_alert",
                            color_scheme="amber",
                        ),
                        _linha_painel(
                            "Taxa atual (AOA/EUR)",
                            State.current_rate_str + " — atualizada " + State.rate_updated_ago_str,
                        ),
                    ),
                    width="100%",
                    padding="1em",
                    border=f"1px solid {rx.color('gray', 6)}",
                    border_radius="0.75em",
                ),
            ),
            rx.divider(),
            # ---- Contratos ----
            rx.heading("Contratos na Base Sepolia", size="6"),
            rx.vstack(
                _link_contrato("EuroVault", VAULT_ADDRESS),
                _link_contrato("EurAoaOracle", ORACLE_ADDRESS),
                _link_contrato("EURC (Circle)", EURC_ADDRESS),
                align="start",
            ),
            spacing="5",
            padding="2em",
            max_width="40em",
            margin="0 auto",
        ),
    )


app = rx.App()
app.add_page(index, on_load=State.atualizar_cofre)
