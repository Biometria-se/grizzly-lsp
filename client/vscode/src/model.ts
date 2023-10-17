export interface ExtensionStatus {
    isActivated: () => boolean;
    setActivated: (status?: boolean) => void;
}

interface SettingsStdio {
    executable: string;
    args: string[];
}

interface SettingsSocket {
    host: string;
    port: number;
}

type SettingsServerConnection = 'socket' | 'stdio';

interface SettingsServer {
    connection: SettingsServerConnection;
}

export interface Settings {
    server: SettingsServer;
    stdio: SettingsStdio;
    socket: SettingsSocket;
    variable_pattern: string[];
    pip_extra_index_url: string;
    use_virtual_environment: boolean;
    diagnostics_on_save_only: boolean;
}
