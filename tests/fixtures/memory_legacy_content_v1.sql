BEGIN TRANSACTION;
CREATE TABLE entries (
        user_id TEXT NOT NULL, project_id TEXT NOT NULL, memory_id TEXT NOT NULL,
        source_id TEXT NOT NULL, memory_key TEXT NOT NULL, conditions TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        state TEXT NOT NULL CHECK (state IN ('active', 'superseded', 'retracted')),
        payload TEXT NOT NULL,
        PRIMARY KEY (user_id, project_id, memory_id),
        UNIQUE (user_id, project_id, memory_key, conditions, version),
        FOREIGN KEY (user_id, project_id, source_id)
            REFERENCES sources (user_id, project_id, source_id)
    );
INSERT INTO "entries" VALUES('legacy-user','mini-pi-fixture','47606bf203d1e22973ff70d90754648ad120ce4e6b92cfa7eede789a34903e7a','legacy-language-1','example_language','[]',1,'superseded','{"draft":{"conditions":[],"end":17,"key":"example_language","kind":"semantic","start":0,"valid_from":"2026-10-20T01:00:00.000000+00:00"},"memory_id":"47606bf203d1e22973ff70d90754648ad120ce4e6b92cfa7eede789a34903e7a","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source":{"recorded_at":"2026-10-20T01:00:00.000000+00:00","role":"user","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source_id":"legacy-language-1","text":"以后学习时用 Python 举例。"},"state":"superseded","valid_to":"2026-10-21T01:00:00.000000+00:00","version":1,"written_at":"2026-10-22T08:31:49.473093+00:00"}');
INSERT INTO "entries" VALUES('legacy-user','mini-pi-fixture','abfe7fa00db136ccb3e3dde59ca8c9000f90d19fb522e16201e83ec017a30b80','legacy-language-2','example_language','[]',2,'active','{"draft":{"conditions":[],"end":24,"key":"example_language","kind":"semantic","start":0,"valid_from":"2026-10-21T01:00:00.000000+00:00"},"memory_id":"abfe7fa00db136ccb3e3dde59ca8c9000f90d19fb522e16201e83ec017a30b80","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source":{"recorded_at":"2026-10-21T01:00:00.000000+00:00","role":"user","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source_id":"legacy-language-2","text":"从现在起，学习时用 JavaScript 举例。"},"state":"active","valid_to":null,"version":2,"written_at":"2026-10-22T08:31:49.478717+00:00"}');
INSERT INTO "entries" VALUES('legacy-user','mini-pi-fixture','b77caaeaf3e26b2a38f45a6ba31868486d28f82c239bf160b64560b84652b019','legacy-study-1','study_time','[]',1,'retracted','{"draft":{"conditions":[],"end":7,"key":"study_time","kind":"semantic","start":0,"valid_from":"2026-10-20T02:00:00.000000+00:00"},"memory_id":"b77caaeaf3e26b2a38f45a6ba31868486d28f82c239bf160b64560b84652b019","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source":{"recorded_at":"2026-10-20T02:00:00.000000+00:00","role":"user","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source_id":"legacy-study-1","text":"周末晚上学习。"},"state":"retracted","valid_to":null,"version":1,"written_at":"2026-10-22T08:31:49.483102+00:00"}');
CREATE TABLE operation_receipts (
        user_id TEXT NOT NULL, project_id TEXT NOT NULL, operation_id TEXT NOT NULL,
        action TEXT NOT NULL CHECK (action IN ('replace', 'retract')),
        request_hash TEXT NOT NULL, memory_key TEXT NOT NULL, conditions TEXT NOT NULL,
        expected_version INTEGER NOT NULL CHECK (expected_version > 0),
        result_memory_id TEXT NOT NULL,
        result_version INTEGER NOT NULL CHECK (result_version > 0),
        source_id TEXT NOT NULL, payload TEXT NOT NULL,
        PRIMARY KEY (user_id, project_id, operation_id),
        FOREIGN KEY (user_id, project_id, result_memory_id)
            REFERENCES entries (user_id, project_id, memory_id),
        FOREIGN KEY (user_id, project_id, source_id)
            REFERENCES sources (user_id, project_id, source_id)
    );
INSERT INTO "operation_receipts" VALUES('legacy-user','mini-pi-fixture','legacy-replace-1','replace','f778c7a6e9a52875a92abfa51f335f1b57fd6ae7d1b53863e47d1ae23d070917','example_language','[]',1,'abfe7fa00db136ccb3e3dde59ca8c9000f90d19fb522e16201e83ec017a30b80',2,'legacy-language-2','{"action":"replace","conditions":[],"expected_version":1,"key":"example_language","operation_id":"legacy-replace-1","request_hash":"f778c7a6e9a52875a92abfa51f335f1b57fd6ae7d1b53863e47d1ae23d070917","result_memory_id":"abfe7fa00db136ccb3e3dde59ca8c9000f90d19fb522e16201e83ec017a30b80","result_version":2,"scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source":{"recorded_at":"2026-10-21T01:00:00.000000+00:00","role":"user","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source_id":"legacy-language-2","text":"从现在起，学习时用 JavaScript 举例。"},"written_at":"2026-10-22T08:31:49.478823+00:00"}');
INSERT INTO "operation_receipts" VALUES('legacy-user','mini-pi-fixture','legacy-retract-1','retract','e3795959440fa0fa699bd78706cafd6b1f9a864820e3d92a258f337668d088c5','study_time','[]',1,'b77caaeaf3e26b2a38f45a6ba31868486d28f82c239bf160b64560b84652b019',1,'legacy-study-withdrawal','{"action":"retract","conditions":[],"expected_version":1,"key":"study_time","operation_id":"legacy-retract-1","request_hash":"e3795959440fa0fa699bd78706cafd6b1f9a864820e3d92a258f337668d088c5","result_memory_id":"b77caaeaf3e26b2a38f45a6ba31868486d28f82c239bf160b64560b84652b019","result_version":1,"scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source":{"recorded_at":"2026-10-22T01:00:00.000000+00:00","role":"user","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source_id":"legacy-study-withdrawal","text":"撤回周末晚上学习的偏好。"},"written_at":"2026-10-22T08:31:49.487385+00:00"}');
CREATE TABLE sources (
        user_id TEXT NOT NULL, project_id TEXT NOT NULL, source_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (user_id, project_id, source_id)
    );
INSERT INTO "sources" VALUES('legacy-user','mini-pi-fixture','legacy-language-1','{"recorded_at":"2026-10-20T01:00:00.000000+00:00","role":"user","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source_id":"legacy-language-1","text":"以后学习时用 Python 举例。"}');
INSERT INTO "sources" VALUES('legacy-user','mini-pi-fixture','legacy-language-2','{"recorded_at":"2026-10-21T01:00:00.000000+00:00","role":"user","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source_id":"legacy-language-2","text":"从现在起，学习时用 JavaScript 举例。"}');
INSERT INTO "sources" VALUES('legacy-user','mini-pi-fixture','legacy-study-1','{"recorded_at":"2026-10-20T02:00:00.000000+00:00","role":"user","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source_id":"legacy-study-1","text":"周末晚上学习。"}');
INSERT INTO "sources" VALUES('legacy-user','mini-pi-fixture','legacy-study-withdrawal','{"recorded_at":"2026-10-22T01:00:00.000000+00:00","role":"user","scope":{"project_id":"mini-pi-fixture","user_id":"legacy-user"},"source_id":"legacy-study-withdrawal","text":"撤回周末晚上学习的偏好。"}');
COMMIT;
