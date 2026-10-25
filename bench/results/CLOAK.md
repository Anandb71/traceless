| photo | ε | GeoCLIP (white-box) | GeoCLIP adaptive (transfer) | LPIPS | SSIM |
|---|---|---|---|---|---|
| abergavenny-book-shop | 2/255 | 21 km → **475 km** | 21 km → **475 km** | 0.0074 | 0.9917 |
| abergavenny-book-shop | 4/255 | 21 km → **475 km** | 21 km → **475 km** | 0.0252 | 0.9729 |
| madrid-jamon-shopfront | 2/255 | 0.9 km → **506 km** | 0.9 km → **506 km** | 0.0041 | 0.9947 |
| madrid-jamon-shopfront | 4/255 | 0.9 km → **506 km** | 0.9 km → **506 km** | 0.0121 | 0.9835 |
| osaka-dotonbori-signs | 2/255 | 0.0 km → **397 km** | 0.0 km → **0.0 km** | 0.0117 | 0.9915 |
| osaka-dotonbori-signs | 4/255 | 0.0 km → **397 km** | 0.0 km → **0.2 km** | 0.0342 | 0.9726 |
| cincinnati-main-st | 2/255 | 0.3 km → **1,052 km** | 0.4 km → **0.4 km** | 0.0061 | 0.9941 |
| cincinnati-main-st | 4/255 | 0.3 km → **1,052 km** | 0.4 km → **1,052 km** | 0.0179 | 0.9806 |
| paris-eiffel-tower | 2/255 | 0.2 km → **8,751 km** | 0.3 km → **0.2 km** | 0.0217 | 0.9889 |
| paris-eiffel-tower | 4/255 | 0.2 km → **8,751 km** | 0.3 km → **8,751 km** | 0.0772 | 0.9567 |
| iowa-rural-blacktop | 2/255 | 307 km → **1,595 km** | 307 km → **190 km** | 0.0049 | 0.9924 |
| iowa-rural-blacktop | 4/255 | 307 km → **1,599 km** | 307 km → **769 km** | 0.0162 | 0.9757 |
| bigsur-pfeiffer-beach | 2/255 | 0.0 km → **7,040 km** | 0.0 km → **7,040 km** | 0.0121 | 0.992 |
| bigsur-pfeiffer-beach | 4/255 | 0.0 km → **8,139 km** | 0.0 km → **8,139 km** | 0.0387 | 0.9732 |
| berlin-shopwindow-reflection | 2/255 | 425 km → **1,950 km** | 635 km → **1,950 km** | 0.0204 | 0.9947 |
| berlin-shopwindow-reflection | 4/255 | 425 km → **1,950 km** | 635 km → **1,950 km** | 0.0573 | 0.9825 |
| tyumen-portrait | 2/255 | 2,385 km → **11,011 km** | 2,360 km → **11,011 km** | 0.0097 | 0.9878 |
| tyumen-portrait | 4/255 | 2,385 km → **11,265 km** | 2,360 km → **11,265 km** | 0.0398 | 0.9572 |
| depew-suburban-street | 2/255 | 307 km → **231 km** | 327 km → **231 km** | 0.0042 | 0.9959 |
| depew-suburban-street | 4/255 | 307 km → **3,169 km** | 327 km → **3,169 km** | 0.0134 | 0.9855 |

Transfer to other model families (Madrid, inside street coverage):

| variant | street matcher (inliers / km) | The Reader |
|---|---|---|
| original | 137 / 0.17 | 8019.68 |
| cloak 2/255 | 141 / 0.17 | 8019.68 |
| cloak 4/255 | 138 / 0.17 | 8019.68 |
