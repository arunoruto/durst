{
  pkgs,
  ...
}:
{

  packages = with pkgs; [
    git
    lazysql
  ];

  scripts = {
    durst.exec = ''uv run durst "$@"'';
  };

  enterShell = ''
    if [ ! -L "$DEVENV_ROOT/.venv" ]; then
        ln -s "$DEVENV_STATE/venv/" "$DEVENV_ROOT/.venv"
    fi
  '';

  languages.python = {
    enable = true;
    # version = "3.12";

    uv = {
      enable = true;
      sync = {
        enable = true;
        groups = [
          "test"
          # "docs"
        ];
      };
    };

    libraries = [ pkgs.zlib ];
  };
}
