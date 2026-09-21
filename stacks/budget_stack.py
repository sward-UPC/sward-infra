from aws_cdk import Stack, aws_budgets as budgets
from constructs import Construct


class BudgetStack(Stack):
    """Avisos de gasto de la cuenta.

    La cuenta funciona con créditos de estudiante, que se agotan y no se
    renuevan. AWS no permite avisar sobre un porcentaje del saldo de créditos, de
    modo que se fija el monto disponible como presupuesto y se avisa al superar
    el 50 % y el 80 % de esa cifra. Dos presupuestos, con propósitos distintos:

    - **Anual**: el consumo total contra los créditos disponibles. Responde
      «cuánto me queda».
    - **Mensual**: un mes suelto que se dispara. Responde «esto se salió de lo
      normal», que es lo que pasa cuando el apagado nocturno falla y la
      infraestructura queda encendida (el modo dev cuesta unos 50 USD al mes si
      corre las 24 horas).

    El correo se suscribe directamente en el presupuesto: no hace falta SNS ni
    confirmar ninguna suscripción.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        correo_alertas: str,
        creditos_usd: float,
        tope_mensual_usd: float,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self._presupuesto(
            "SwardPresupuestoAnual",
            nombre="sward-creditos-anual",
            unidad_de_tiempo="ANNUALLY",
            monto=creditos_usd,
            correo=correo_alertas,
        )

        self._presupuesto(
            "SwardPresupuestoMensual",
            nombre="sward-gasto-mensual",
            unidad_de_tiempo="MONTHLY",
            monto=tope_mensual_usd,
            correo=correo_alertas,
        )

    def _presupuesto(
        self,
        construct_id: str,
        nombre: str,
        unidad_de_tiempo: str,
        monto: float,
        correo: str,
    ) -> budgets.CfnBudget:
        destinatario = [
            budgets.CfnBudget.SubscriberProperty(
                subscription_type="EMAIL", address=correo
            )
        ]

        def aviso(
            umbral: float, tipo: str
        ) -> budgets.CfnBudget.NotificationWithSubscribersProperty:
            return budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    comparison_operator="GREATER_THAN",
                    notification_type=tipo,
                    threshold=umbral,
                    threshold_type="PERCENTAGE",
                ),
                subscribers=destinatario,
            )

        return budgets.CfnBudget(
            self,
            construct_id,
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=nombre,
                budget_type="COST",
                time_unit=unidad_de_tiempo,
                budget_limit=budgets.CfnBudget.SpendProperty(amount=monto, unit="USD"),
                # Los créditos cuentan como gasto: de lo contrario el aviso
                # llegaría recién cuando se hubieran agotado y empezara a
                # cobrarse la tarjeta, que es justo lo que se quiere evitar.
                cost_types=budgets.CfnBudget.CostTypesProperty(
                    include_credit=True,
                    include_discount=True,
                    include_other_subscription=True,
                    include_recurring=True,
                    include_refund=False,
                    include_subscription=True,
                    include_support=True,
                    include_tax=True,
                    include_upfront=True,
                    use_amortized=False,
                    use_blended=False,
                ),
            ),
            notifications_with_subscribers=[
                aviso(50, "ACTUAL"),
                aviso(80, "ACTUAL"),
                # Previsión: avisa antes de llegar, no cuando ya pasó.
                aviso(100, "FORECASTED"),
            ],
        )
