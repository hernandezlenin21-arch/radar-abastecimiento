# Matriz de fuentes

Verificado el 16 de octubre de 2026. "Verificado" significa que el endpoint y su formato están documentados públicamente por el proveedor; la conexión en vivo se confirma en la primera ejecución del proceso automático (la pestaña **Fuentes y calidad** muestra el resultado real de cada consulta).

| Indicador | Proveedor | Serie / clave | URL de acceso | Método | Costo | Frecuencia | Tipo de precio |
|---|---|---|---|---|---|---|---|
| Maíz amarillo | Banco Mundial (Pink Sheet) | `Maize` | https://www.worldbank.org/en/research/commodity-markets → CMO-Historical-Data-Monthly.xlsx | Descarga Excel | Gratis, sin clave | Mensual | Promedio mensual, US No.2 Golfo FOB |
| Soya en grano | Banco Mundial | `Soybeans` | ídem | Descarga Excel | Gratis | Mensual | Promedio mensual, CIF Rotterdam |
| Harina de soya | Banco Mundial | `Soybean meal` | ídem | Descarga Excel | Gratis | Mensual | Promedio mensual, CIF Rotterdam |
| Trigo (HRW) | Banco Mundial | `Wheat, US HRW` | ídem | Descarga Excel | Gratis | Mensual | Promedio mensual, Golfo FOB |
| Aceite de soya | Banco Mundial | `Soybean oil` | ídem | Descarga Excel | Gratis | Mensual | Promedio mensual |
| Aceite de palma | Banco Mundial | `Palm oil` | ídem | Descarga Excel | Gratis | Mensual | Promedio mensual, CIF Rotterdam |
| Aceite de maní | Banco Mundial | `Groundnut oil` | ídem | Descarga Excel | Gratis | Mensual | Promedio mensual |
| Carbón térmico | Banco Mundial | `Coal, Australian` | ídem | Descarga Excel | Gratis | Mensual | Promedio mensual, Newcastle FOB |
| Oro / Plata | Banco Mundial | `Gold`, `Silver` | ídem | Descarga Excel | Gratis | Mensual | Promedio mensual |
| Carne bovina | Banco Mundial | `Beef` | ídem | Descarga Excel | Gratis | Mensual | Carne procesada, Australia/NZ |
| DDGS | USDA AMS MyMarketNews | Reporte `3511` (Corn Distillers Dried Grain 10%) | https://marsapi.ams.usda.gov/services/v1.2/reports/3511 · https://mymarketnews.ams.usda.gov/viewReport/3511 | API MARS (Basic Auth) | Gratis, con registro | Según publicación | Físico, USD/short ton → USD/t |
| Petróleo WTI | FRED (EIA) | `DCOILWTICO` | https://fred.stlouisfed.org/series/DCOILWTICO | API REST | Gratis, con clave | Diaria | Spot Cushing |
| Petróleo Brent | FRED (EIA) | `DCOILBRENTEU` | https://fred.stlouisfed.org/series/DCOILBRENTEU | API REST | Gratis, con clave | Diaria | Spot Europa |
| Diésel ULSD NY Harbor | FRED (EIA) | `DDFUELNYH` | https://fred.stlouisfed.org/series/DDFUELNYH | API REST | Gratis, con clave | Diaria | Spot mayorista, USD/gal → USD/L |
| Diésel minorista EE.UU. | EIA | `EMD_EPD2D_PTE_NUS_DPG` | https://api.eia.gov/v2/petroleum/pri/gnd/data/ | API REST v2 | Gratis, con clave | Semanal | Minorista |
| Gas natural Henry Hub | FRED (EIA) | `DHHNGSP` | https://fred.stlouisfed.org/series/DHHNGSP | API REST | Gratis, con clave | Diaria | Spot |
| Índice del dólar | FRED | `DTWEXBGS` | https://fred.stlouisfed.org/series/DTWEXBGS | API REST | Gratis, con clave | Diaria | Índice |
| Bono 10 años EE.UU. | FRED | `DGS10` | https://fred.stlouisfed.org/series/DGS10 | API REST | Gratis, con clave | Diaria | Tasa % |
| GSCPI | Fed de Nueva York | `gscpi_data.xlsx` | https://www.newyorkfed.org/research/policy/gscpi | Descarga Excel | Gratis, sin clave | Mensual (4.º día hábil) | Índice (desv. est.) |
| ONI (El Niño/La Niña) | NOAA CPC | `oni.ascii.txt` | https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt | Texto oficial | Gratis | Mensual | Anomalía °C |
| Estado ENSO | NOAA CPC | Discusión ENSO | https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml | Página oficial | Gratis | Mensual | Evento |
| Ciclones activos | NOAA NHC | `CurrentStorms.json` | https://www.nhc.noaa.gov/CurrentStorms.json | JSON oficial | Gratis | Por aviso (≈ 6 h) | Evento |
| Noticias | GDELT Project | DOC 2.0 API | https://api.gdeltproject.org/api/v2/doc/doc | API REST | Gratis, sin clave (≤ 1 consulta/5 s) | Continua | Titulares (señal de prensa) |

## Integraciones pendientes o no incluidas

| Fuente | Motivo | Alternativa implementada |
|---|---|---|
| CME Group / CBOT (futuros) | Requiere licencia de datos de mercado para redistribuir | Promedios mensuales del Banco Mundial + físico de USDA AMS |
| USDA WASDE / FAS PSD | API con registro; prevista para fase 2 | Se monitorea vía noticias ("WASDE") |
| Ganado en pie (USDA AMS) | El número de reporte debe validarse antes de activarlo | Carne bovina (Banco Mundial); indicador desactivado en `config/indicators.yaml` |
| Oro/plata diarios | No hay fuente oficial abierta con permiso de redistribución | Promedio mensual del Banco Mundial |
| Canal de Panamá, autoridades portuarias | No publican API abierta | Titulares de prensa marcados "señal a confirmar" |
| UNCTAD, FAO | Estadísticas anuales/trimestrales poco útiles para monitoreo diario | Fase 2 (FAO Food Price Index mensual) |
| Precios locales Nicaragua (diésel en bomba, energía, fletes) | No son públicos en formato automatizable | Ingresar en el simulador como valores del usuario |

## Reglas de unidades

- 1 short ton = 907.18474 kg → USD/short ton × 1.10231 = USD/t
- Bushel de maíz = 56 lb (25.401 kg) → USD/bu × 39.368 = USD/t
- Bushel de soya y trigo = 60 lb (27.216 kg) → USD/bu × 36.744 = USD/t
- 1 galón EE.UU. = 3.785411784 L
- 1 cwt = 100 lb = 45.359237 kg
- Barril (bbl), MMBtu y onza troy se mantienen en su unidad original (no tiene sentido convertirlos a toneladas).
