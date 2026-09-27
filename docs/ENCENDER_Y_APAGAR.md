# Encender y apagar SWARD en AWS

**Regla:** nada se enciende sin que Jorge lo indique. Los créditos (100 USD, sin
renovación) solo se gastan en las pruebas con participantes y en los ensayos
previos. Antes de cada encendido se anuncia el costo por hora.

## Atajo: mientras los stacks sigan en pie

Si el apagado anterior fue **detener y no destruir** —que es lo normal entre una
sesión y la siguiente, porque hay datos— no hay nada que desplegar:

```bash
./encender.sh     # NAT, base y Moodle, y después los servicios
./apagar.sh       # al revés, y la NAT al final
```

Los dos descubren solos los identificadores, así que siguen valiendo si algún
stack se vuelve a crear. `encender.sh` no sube los servicios si la base no llega
a `available`: quedarían reintentando contra una base apagada y gastando igual.

## Durante el estudio no se apaga de noche

Decidido el 27 de septiembre, con la factura real delante y no con la estimación.

Los participantes y su profesor dan por hecho que SWARD es una web normal,
disponible cuando entren. Apagarla de noche los dejaría fuera sin explicación, y
lo que se ahorra no compensa:

| | USD al día |
|---|---|
| Un día entero con **todo encendido** (26 de septiembre, desplegando y probando) | **1,20** |
| La parte que se cobra **aunque esté detenido**: balanceador 0,29 · IP y red 0,26 · almacenamiento de la base 0,30 · secretos 0,10 | **~0,95** |
| Lo que ahorra de verdad apagar una noche entera | **~0,25** |

El balanceador, las IP fijas, los discos, los once secretos y la zona privada de
DNS (`sward.local`, 0,50 al mes, la que usan los servicios para encontrarse) se
cobran igual. Solo Fargate, la base y las dos EC2 dependen de estar encendido.

**Con todo encendido son unos 1,2 a 1,5 USD al día**, así que los 120 USD de
crédito dan para unos **ochenta días seguidos**. El estudio dura semanas. No hay
razón para apagarlo mientras esté en marcha, y sí hay una para no hacerlo: que
alguien entre y no encuentre nada.

`apagar.sh` sigue siendo lo correcto **después** del estudio, o en un hueco de
varios días. Para eso está. Bajar del suelo de 0,95 solo se consigue destruyendo
los stacks, y eso se lleva los datos.

**El aviso está puesto:** dos presupuestos con alertas al 50 % y al 80 % del gasto
y una por previsión —`sward-creditos-anual` (100 USD) y `sward-gasto-mensual`
(50 USD)—, así que si algo se desmadra llega el correo antes de quemar el crédito.

El resto de este documento es el despliegue completo, para cuando sí se destruyó.

---

Todos los comandos se corren desde `sward-infra`, con el usuario IAM
`sward-deploy` configurado (`aws sts get-caller-identity`) y:

```bash
CDK="cdk --app '.venv\Scripts\python.exe app.py'"   # en Windows, con barras invertidas
```

## Qué queda siempre y qué se enciende

| Stack | Siempre | Costo aproximado |
|---|---|---|
| `CDKToolkit`, `SwardPresupuesto` | sí | 0 |
| `SwardStorage` (buckets de material y modelos) | sí | centavos al mes |
| `SwardEcr` (imágenes de las lambdas, ~4 GB) | sí | ~0,40 USD/mes |
| `SwardSecrets` (11 secretos) | a decidir | 4,40 USD/mes si queda |
| `SwardNetworking` (VPC + NAT t3.nano) | no | ~0,010 USD/h |
| `SwardMoodle` (t3.small + disco + IP) | no | ~0,030 USD/h |
| `SwardDatabase` (RDS t3.micro cifrada) | no | ~0,021 USD/h |
| `SwardServices` (7 tasks Fargate + ALB) | no | ~0,10 USD/h con Spot; ~0,16 sin Spot |
| `SwardLambdas`, `SwardCloudfront` | no | casi 0 en uso |

**Todo encendido:** unos **0,15 USD por hora** en un ensayo (con Spot) y unos
**0,23 USD por hora** en una sesión con participantes (`-c spot=false`). Un
ensayo de 4 horas cuesta menos de 1 USD. Lo caro es olvidarlo encendido: 24 h
son 3,6 a 5,5 USD.

Precios on-demand de us-east-1 (septiembre de 2026), sin impuestos. El gasto
real se ve en `aws budgets describe-budgets --account-id 326946550895`.

## Encender (ensayo o sesión)

1. **Red, secretos, almacenamiento, registro y base:**
   ```bash
   $CDK deploy SwardNetworking SwardSecrets SwardStorage SwardEcr SwardDatabase --require-approval never
   ```
2. **Correo:** Jorge pega la contraseña de aplicación de Gmail en el secreto
   `sward/smtp` (consola → Secrets Manager → `sward/smtp` → Editar):
   `{"email_backend":"smtp","smtp_user":"sward.proyecto@gmail.com","smtp_password":"<16 letras>","email_remitente":"SWARD <sward.proyecto@gmail.com>"}`
3. **Imágenes de las lambdas y modelo:**
   ```bash
   ./push_lambda_images.sh
   aws s3 cp <modelo.pth> s3://sward-models-326946550895/sakt/moodle/model.pth
   ```
4. **Moodle** (tarda ~10 min más en instalarse después de que el stack termina):
   ```bash
   $CDK deploy SwardMoodle --require-approval never
   ```
5. **SWARD** (en sesión con participantes, agregar `-c spot=false`):
   ```bash
   $CDK deploy SwardServices SwardLambdas SwardCloudfront -c notif_lambda=true --require-approval never
   ```
6. **Integración con Moodle:** reiniciar integracion-lms cuando Moodle ya guardó
   su token en `sward/moodle-token` (lo lee al arrancar):
   ```bash
   aws ecs update-service --cluster sward-cluster --service integracion-lms --force-new-deployment
   ```
7. **Frontend:** la URL de la API cambia con cada CloudFront nuevo. Poner el
   output `ApiUrl` de `SwardCloudfront` en `VITE_API_URL` de
   `sward-frontend/.github/workflows/deploy-pages.yml` y subir a `main`
   (GitHub Pages se republica solo).
8. **Cursos y participantes:** `cargar_cursos.php` en Moodle (por Session
   Manager) y `crear_participantes.py` contra la URL de Moodle.

## Apagar

**Después de un ensayo** (no hay datos que conservar): destruir todo lo que se
encendió, en orden inverso.

```bash
$CDK destroy SwardCloudfront SwardLambdas SwardServices SwardMoodle SwardDatabase SwardNetworking --force
```

Las lambdas en VPC tardan en liberar sus interfaces de red: el destroy de
`SwardLambdas` y `SwardNetworking` puede tomar 20 a 40 minutos.

**Secretos con nombre fijo:** al destruir su stack, AWS los deja 30 días en
papelera, y volver a desplegar con el mismo nombre **falla**. Borrarlos del todo:

```bash
aws secretsmanager delete-secret --secret-id sward/moodle-admin --force-delete-without-recovery
aws secretsmanager delete-secret --secret-id sward/rds/shared --force-delete-without-recovery
```

(Y los once de `sward/` si también se destruye `SwardSecrets`.) El bucket de
respaldos de Moodle se conserva (RETAIN): borrarlo a mano si solo tuvo el ensayo.

**Entre la fase 1 y la fase 2, y cada noche** (hay datos: no destruir). Eso es lo
que hace `./apagar.sh`: los servicios a cero, luego Moodle y la base
(`aws rds stop-db-instance`, se reinicia sola a los 7 días) y la NAT al final.
Siguen cobrando el ALB, los discos, las IP y los secretos: ~1,2 a 1,4 USD por día.

**Después de la fase 2:** respaldar la base (`pg_dump` a S3) y Moodle (el
respaldo diario ya va a S3), y destruir como en un ensayo.

## Verificar que quedó apagado

```bash
aws ec2 describe-instances --filters Name=instance-state-name,Values=running --query "Reservations[].Instances[].InstanceId"
aws rds describe-db-instances --query "DBInstances[].DBInstanceStatus"
aws ec2 describe-addresses --query "Addresses[].PublicIp"
aws elbv2 describe-load-balancers --query "LoadBalancers[].LoadBalancerName"
```

Las cuatro listas deben salir vacías.
