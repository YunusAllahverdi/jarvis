"""UI aksiyon kanalı — ajanın kullanıcının ekranını sürebilmesi.

Defterin "diğer her şeyin dayandığı temel" dediği parça budur: bir araç
çağrısının panele dönüşmesi. Ajan "notlarına bakalım" dediğinde notlar
paneli açılır; kullanıcının ayrıca tıklaması gerekmez.

MİMARİNİN TEK CÜMLESİ: Ajan ekrana METİN GÖNDEREMEZ, yalnızca VAR OLAN bir
paneli açmasını isteyebilir.

Bu ayrım kanalın güvenliğinin tamamıdır. Ajan serbest içerik gönderebilseydi,
kanal bir "kullanıcıya istediğini gösterme" aracı olurdu ve bir web
sayfasından okunan metin kullanıcının ekranında Jarvis'in sözü gibi
görünebilirdi. Kapalı bir panel kümesinden seçim yapmak, en kötü ihtimalle
yanlış panelin açılması demektir.

İzin seviyesi READ'tir ve bu bilinçlidir: panel açmak dosyaya dokunmaz, komut
çalıştırmaz ve geri alınamaz bir şey yapmaz — kullanıcı paneli kapatabilir.
Onay kapısına takılsaydı, "notlarını açayım mı?" diye sorup beklemek
etkileşimi kolaylaştırmak yerine zorlaştırırdı.
"""
