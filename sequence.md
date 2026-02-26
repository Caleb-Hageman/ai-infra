```mermaid
    sequenceDiagram
    participant FE as Frontend (Product Team)
    participant GW as GCP API Gateway
    participant API as FastAPI (Cloud Run)
    participant DB as PostgreSQL + PGVector (e2-micro)
    participant GCS as Google Cloud Storage
    participant GPU as vLLM (Cloud Run GPU)

    FE->>GW: POST /chat (Prompt + API_Key)

    alt Over Limit
        GW-->>FE: 429 Too Many Requests
    else Within Limit
        GW->>API: Forward Request (Authorized)
        
        rect rgba(240, 240, 240, 0.1)
            API->>API: Generate Embedding
            
            API->>DB: Vector Search (Filter by Team_ID)
            DB-->>API: Relevant Chunks + Metadata
            
            par Parallel Processing
                API->>GCS: Request Pre-signed URL
                GCS-->>API: Source Citation URL
            and
                API->>GPU: Stream Prompt + Context
                loop Token Stream
                    GPU-->>API: Stream Text Chunk
                    API-->>FE: Stream to UI
                end
            end
            
            API->>DB: Save Full Prompt/Response (History)
        end
        
        API-->>FE: [Stream Done] + Final Citation URL
    end
```