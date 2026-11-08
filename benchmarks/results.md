| app | escenario | concurrencia | media (s) | desviación (s) |
|---|---|---:|---:|---:|
| sync | carga masiva | 1 | 21.2401 | 0.5714 |
| async | carga masiva | 10 | 5.1759 | 1.4341 |
| sync | CRUD | 1 | 1.0092 | 1.2096 |
| async | CRUD | 1 | 0.3021 | 0.0182 |
| sync | consultas | 1 | 0.3414 | 0.0616 |
| async | consultas | 1 | 0.1354 | 0.0190 |
| sync | consultas | 10 | 1.1100 | 0.3315 |
| async | consultas | 10 | 1.0208 | 0.0791 |
| sync | consultas | 50 | 3.0187 | 0.0854 |
| async | consultas | 50 | 2.8637 | 0.1400 |
| sync | consultas | 100 | 5.2551 | 0.2653 |
| async | consultas | 100 | 5.1011 | 0.2023 |
