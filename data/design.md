# DATA

``` bash
data/
├── providers/ # 外部 adapter
│ ├── akshare.py
│ ├── tushare.py
│ └── tdx.py
│
├── market/ # canonical Market Data domain
│ ├── contracts.py
│ ├── model.py
│ ├── schema.py
│ ├── capture.py
│ ├── normalize.py
│ ├── revision.py
│ ├── ingestion.py
│ ├── quality.py
│ ├── reconciliation.py
│ └── serving.py
│
├── dataset/ # canonical PIT Dataset domain
│ ├── model.py
│ ├── manifest.py
│ ├── catalog.py
│ ├── resolver.py
│ └── reader.py
│
└── storage/ # domain-neutral physical primitives
├── objects.py
└── parquet.py

research/
└── features/
├── model.py
├── registry.py
├── compute.py
└── materialize.py
```
