# Context

Precedence от низшего к высшему:

1. upstream defaults;
2. global kit;
3. project committed configuration;
4. user global local overrides;
5. user project-specific local overrides.

Более высокий слой не может ослабить `enforced`/`locked` policy, отключить mandatory validation или сделать user-local model допустимой для committed definition. В начале session фиксируется revision kit; активная task не переключается на новый revision посередине работы.
